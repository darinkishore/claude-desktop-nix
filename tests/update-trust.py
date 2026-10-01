#!/usr/bin/env python3
"""Offline rejection tests using an authentic InRelease/Packages snapshot.

Run with gpg/gpgv, Nix and jq on PATH:
  python3 tests/update-trust.py /path/to/snapshot
The snapshot directory must contain InRelease and Packages from Anthropic.
No test downloads or executes the application.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SNAPSHOT = Path(sys.argv.pop(1)).resolve()
REPO = Path(__file__).resolve().parent.parent


class UpdateTrust(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'pkgs').mkdir()
        for name in ('update.sh', 'anthropic-key.asc'):
            shutil.copyfile(REPO / 'pkgs' / name, self.root / 'pkgs' / name)
        shutil.copyfile(REPO / 'sources.json', self.root / 'sources.json')
        for name in ('InRelease', 'Packages'):
            shutil.copyfile(SNAPSHOT / name, self.root / name)
        tools = self.root / 'bin'
        tools.mkdir()
        curl = tools / 'curl'
        curl.write_text(f'''#!{sys.executable}
import pathlib, shutil, sys
args = sys.argv[1:]
url = next(a for a in args if a.startswith('https://'))
name = url.rsplit('/', 1)[1]
assert name in ('InRelease', 'Packages'), url
shutil.copyfile(pathlib.Path(__file__).parent.parent / name,
                args[args.index('-o') + 1])
''')
        curl.chmod(0o755)
        prefetch = tools / 'nix-prefetch-url'
        # A corrupt downloaded artifact; no network is involved.
        prefetch.write_text('#!/bin/sh\nprintf "%064d\\n" 0\n')
        prefetch.chmod(0o755)
        self.env = dict(os.environ, PATH=str(tools) + ':' + os.environ['PATH'])

    def pin(self, **changes):
        path = self.root / 'sources.json'
        data = json.loads(path.read_text())
        if 'version' in changes:
            data['version'] = changes['version']
        if 'hash' in changes:
            data['systems']['x86_64-linux']['hash'] = changes['hash']
        path.write_text(json.dumps(data))

    def run_update(self, error=None):
        pin = self.root / 'sources.json'
        before = pin.read_bytes()
        result = subprocess.run(['bash', str(self.root / 'pkgs/update.sh')],
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(pin.read_bytes(), before, 'updater modified pin')
        if error is None:
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('changed=false', result.stdout)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn(error, result.stderr)

    def test_authentic_same_version(self):
        self.run_update()

    def test_modified_signed_metadata(self):
        path = self.root / 'InRelease'
        path.write_bytes(path.read_bytes().replace(b'Origin: Anthropic', b'Origin: Attacker!'))
        self.run_update('BAD signature')

    def test_modified_package_index(self):
        path = self.root / 'Packages'
        path.write_bytes(path.read_bytes() + b'\n')
        self.run_update('Packages does not match signed Release')

    def test_changed_existing_pin(self):
        self.pin(hash='sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=')
        self.run_update('existing pin differs from signed index')

    def test_version_rollback(self):
        self.pin(version='999.0.0')
        self.run_update('refusing version rollback')

    def test_corrupt_download(self):
        self.pin(version='0.0.0')
        self.run_update('hash mismatch')


if __name__ == '__main__':
    unittest.main()
