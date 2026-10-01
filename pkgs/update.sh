#!/usr/bin/env bash
# Bump sources.json to the newest amd64 build in Anthropic's APT index.
#
# Prints nothing but diagnostics on stderr; writes sources.json in place and
# emits `version=<v>` / `changed=<true|false>` on stdout as KEY=VALUE lines so
# CI can consume it. Exits non-zero on any inconsistency — a wrong hash must
# fail the updater, never land silently.
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
sources_json="$repo_root/sources.json"

base_url="https://downloads.claude.ai/claude-desktop/apt/stable"
index_path="main/binary-amd64/Packages"
index_url="$base_url/dists/stable/$index_path"

log() { printf '%s\n' "$*" >&2; }

# This key is vendored, not downloaded on each update. Its primary fingerprint
# is published by Anthropic's installation documentation (see VENDOR.md).
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -m700 "$work/gnupg"
export GNUPGHOME="$work/gnupg"
fingerprint=$(gpg --batch --with-colons --show-keys "$repo_root/pkgs/anthropic-key.asc" \
  | awk -F: '$1 == "fpr" { print $10; exit }')
[ "$fingerprint" = "31DDDE24DDFAB679F42D7BD2BAA929FF1A7ECACE" ] \
  || { log "ERROR: unexpected Anthropic signing key"; exit 1; }
gpg --batch --dearmor --output "$work/keyring.gpg" "$repo_root/pkgs/anthropic-key.asc"
curl -fsSL --proto '=https' --proto-redir '=https' --retry 3 --retry-delay 2 \
  "$base_url/dists/stable/InRelease" -o "$work/InRelease"
gpgv --keyring "$work/keyring.gpg" --output "$work/Release" "$work/InRelease"

log "fetching $index_url"
curl -fsSL --proto '=https' --proto-redir '=https' --retry 3 --retry-delay 2 \
  "$index_url" -o "$work/Packages"
# Check the signed metadata's freshness, identity, size and index digest before
# parsing a single package. An expired/future index cannot roll back our pin.
python3 - "$work/Release" "$work/Packages" "$index_path" <<'PY'
import datetime, email.utils, hashlib, pathlib, sys
release, packages, index_path = sys.argv[1:]
fields = {}
for line in pathlib.Path(release).read_text().splitlines():
    if line and not line[0].isspace() and ':' in line:
        key, value = line.split(':', 1)
        if key in fields:
            raise SystemExit('ERROR: duplicate Release field')
        fields[key] = value.strip()
    elif line.startswith(' ') and key == 'SHA256':
        digest, size, path = line.split()
        if path == index_path:
            if 'index' in fields:
                raise SystemExit('ERROR: duplicate index digest')
            fields['index'] = (digest, int(size))
if fields.get('Origin') != 'Anthropic' or fields.get('Suite') != 'stable':
    raise SystemExit('ERROR: unexpected repository identity')
now = datetime.datetime.now(datetime.timezone.utc)
published = email.utils.parsedate_to_datetime(fields['Date'])
expires = email.utils.parsedate_to_datetime(fields['Valid-Until'])
if published > now + datetime.timedelta(minutes=5) or not published < now < expires:
    raise SystemExit('ERROR: expired or future Release metadata')
data = pathlib.Path(packages).read_bytes()
if fields['index'] != (hashlib.sha256(data).hexdigest(), len(data)):
    raise SystemExit('ERROR: Packages does not match signed Release')
PY
index=$(cat "$work/Packages")

# One "version<TAB>filename<TAB>sha256" line per stanza, then pick the highest
# version. `sort -V` is sufficient for upstream's strictly numeric x.y.z scheme.
newest=$(
  printf '%s\n' "$index" | awk '
    /^Package: /  { pkg = $2 }
    /^Version: /  { ver = $2 }
    /^Filename: / { fn  = $2 }
    /^SHA256: /   { sha = $2 }
    /^$/ {
      if (pkg == "claude-desktop" && ver != "" && fn != "" && sha != "")
        print ver "\t" fn "\t" sha
      pkg = ver = fn = sha = ""
    }
    END {
      if (pkg == "claude-desktop" && ver != "" && fn != "" && sha != "")
        print ver "\t" fn "\t" sha
    }
  ' | sort -V -k1,1 | tail -n1
)

[ -n "$newest" ] || { log "ERROR: no claude-desktop stanza found in the index"; exit 1; }

version=$(cut -f1 <<<"$newest")
filename=$(cut -f2 <<<"$newest")
index_sha=$(cut -f3 <<<"$newest")
url="$base_url/$filename"

[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ \
   && "$filename" = "pool/main/c/claude-desktop/claude-desktop_${version}_amd64.deb" \
   && "$index_sha" =~ ^[0-9a-f]{64}$ ]] \
  || { log "ERROR: unexpected package version, path or digest"; exit 1; }
index_sri=$(nix hash convert --hash-algo sha256 --to sri "$index_sha")

log "newest upstream version: $version"
log "url:                     $url"
log "sha256 (from index):     $index_sha"

current=$(jq -r '.version' "$sources_json")
if [ "$(printf '%s\n' "$current" "$version" | sort -V | head -n1)" != "$current" ]; then
  log "ERROR: refusing version rollback from $current to $version"
  exit 1
fi
if [ "$current" = "$version" ]; then
  [ "$(jq -r '.systems."x86_64-linux".url' "$sources_json")" = "$url" ] \
    && [ "$(jq -r '.systems."x86_64-linux".hash' "$sources_json")" = "$index_sri" ] \
    || { log "ERROR: existing pin differs from signed index"; exit 1; }
  log "sources.json already at $version — nothing to do"
  echo "version=$version"
  echo "changed=false"
  exit 0
fi
log "current sources.json version: $current"

# Fetch into the store and take the hash from Nix itself rather than trusting
# the index blindly...
log "prefetching..."
prefetched=$(nix-prefetch-url --type sha256 "$url")
sri=$(nix hash convert --hash-algo sha256 --to sri "$prefetched")

# ...then cross-check against what the signed index advertises. A divergence
# means the pool object changed under a published hash: refuse to proceed.
if [ "$sri" != "$index_sri" ]; then
  log "ERROR: hash mismatch for $url"
  log "  index advertises: $index_sri"
  log "  download hashes:  $sri"
  exit 1
fi
log "hash verified:           $sri"

tmp="$work/sources.json"
jq --arg version "$version" \
   --arg url "$url" \
   --arg hash "$sri" \
   '.version = $version
    | .systems."x86_64-linux".url = $url
    | .systems."x86_64-linux".hash = $hash' \
   "$sources_json" >"$tmp"
mv "$tmp" "$sources_json"

log "sources.json updated: $current -> $version"
echo "version=$version"
echo "changed=true"
