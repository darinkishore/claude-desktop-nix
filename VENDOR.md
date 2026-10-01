# Darin's vendor branch

Based on stslex/claude-desktop-nix at
`4884bd8615aa62501c3ac693409b1af333e7fe61`. Deployment uses this fork's
`vendor` branch, pinned by nix-config's flake.lock. Upstream packaging changes
must be reviewed before they are merged. GitHub Actions is disabled on this
fork, and the inherited update/sync workflows are removed on this branch.
There are no automatic version bumps or upstream merges.

`pkgs/update.sh` now verifies the complete APT chain:

1. The vendored key's primary fingerprint is
   `31DDDE24DDFAB679F42D7BD2BAA929FF1A7ECACE`.
2. `gpgv` verifies InRelease using only that key.
3. Signed Release metadata must identify Anthropic/stable, be current, and
   match the downloaded Packages index's SHA-256 and byte count.
4. The package's path, version and SHA-256 must be well-formed. Version
   rollbacks and changed hashes for an existing version fail.
5. The downloaded .deb must match the authenticated package digest before
   sources.json can change. Nix enforces that fixed hash during every build.

Key downloaded from https://downloads.claude.ai/claude-desktop/key.asc;
fingerprint cross-checked against Anthropic's official instructions:
https://support.claude.com/en/articles/10065433-install-claude-desktop
Key rotations require deliberate review and changes to both the vendored key
and the expected fingerprint. Do not bypass signature/hash failures.

Manual update: `nix develop -c bash pkgs/update.sh`, build and run the flake's
checks, review and commit the diff, then `vendor bump claude-desktop` from
nix-config and `just sys`. The vendor CLI manages the working clone at
`~/vendor/github.com/stslex/claude-desktop-nix`.

The packaging and artifact are pinned; the application is still proprietary
Anthropic code and talks to Anthropic's service. The Code tab can download
its own CLI/uv at runtime, and configured MCP servers/extensions can introduce
their own dependencies. This fork does not make those runtime downloads
reproducible or establish that the closed-source app is harmless.

On Dusk, the ambient `LD_AUDIT` runtime-compat hook causes this GnuPG build
to abort with stack smashing before it runs. Invoke the update command as
`env -u LD_AUDIT -u LD_LIBRARY_PATH nix develop -c bash pkgs/update.sh` there
so these Nix-built verification tools use their own library closure. This
does not change the machine-wide compatibility configuration.
