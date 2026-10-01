# Claude Desktop vendor fork

Read VENDOR.md before changing packaging or sources.json. This is a manual
review branch; do not restore automatic updates/upstream merges. Keep GitHub
Actions disabled on the fork. Verify the complete pinned-key APT signature
and hash chain; never bypass a verification failure or weaken sandbox checks.

Working clone: ~/vendor/github.com/stslex/claude-desktop-nix. nix-config owns
the vendor manifest, deployment branch and locked revision. Use jj here and
commit owned paths; `vendor bump claude-desktop` in nix-config pushes HEAD to
the fork's vendor branch and updates that input. Deploy with `just sys`.

Run the packaging flake checks against nix-config's locked nixpkgs, and the
offline updater tests against an authentic current InRelease/Packages
snapshot (`python3 tests/update-trust.py /path/to/snapshot`). See VENDOR.md
for Dusk's ambient LD_AUDIT/GnuPG incompatibility and invocation.

Startup verification must use temporary XDG config/cache/data directories.
Do not touch an existing Claude profile or log in as part of smoke tests.
