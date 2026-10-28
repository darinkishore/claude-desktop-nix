"""Check both upstream layouts and fail-closed archive handling."""

import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("shim", Path(__file__).parents[1] / "pkgs/browser-shim.py")
shim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shim)
SOURCE = b"#!/bin/sh\n//usr/bin/true; one\n//usr/bin/true; two\n//usr/bin/true; three\n"
TRUE = "/nix/store/test-coreutils/bin/true"


def fixture(directory, *, packed=True):
    entries = {"unrelated": {"size": 4, "offset": "0"}}
    if packed:
        entries["resources"] = {"files": {shim.NAME: {
            "offset": "4", "size": len(SOURCE), "executable": True,
            "integrity": {"algorithm": "SHA256", "blockSize": 4194304,
                          "hash": hashlib.sha256(SOURCE).hexdigest(),
                          "blocks": [hashlib.sha256(SOURCE).hexdigest()]},
        }}}
    else:
        (directory / shim.NAME).write_bytes(SOURCE)
    encoded = json.dumps({"files": entries}, separators=(",", ":")).encode()
    padded = encoded + b"\0" * (-len(encoded) % 4)
    (directory / "app.asar").write_bytes(
        struct.pack("<4I", 4, len(padded) + 8, len(padded) + 4, len(encoded))
        + padded + b"keep" + (SOURCE if packed else b""))


class BrowserShim(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_packed_preserves_payload_and_other_entries(self):
        fixture(self.root)
        _, before = shim.locate(self.root)
        shim.patch(self.root, TRUE)
        source, after = shim.locate(self.root)  # also verifies updated integrity
        self.assertEqual(source, SOURCE.replace(b"//usr/bin/true;", ("/" + TRUE + ";").encode()))
        self.assertEqual(before[2]["files"]["unrelated"], after[2]["files"]["unrelated"])
        self.assertEqual(before[1][before[3]:], after[1][after[3]:-len(source)])

    def test_legacy_layout_preserves_archive(self):
        fixture(self.root, packed=False)
        before = (self.root / "app.asar").read_bytes()
        shim.patch(self.root, TRUE)
        self.assertEqual((self.root / "app.asar").read_bytes(), before)
        self.assertNotIn(b"//usr/bin/true;", shim.locate(self.root)[0])

    def test_tampered_payload_refused(self):
        fixture(self.root)
        p = self.root / "app.asar"
        p.write_bytes(p.read_bytes()[:-1] + b"!")
        with self.assertRaisesRegex(ValueError, "integrity mismatch"):
            shim.patch(self.root, TRUE)

    def test_ambiguous_layout_refused(self):
        fixture(self.root)
        (self.root / shim.NAME).write_bytes(SOURCE)
        with self.assertRaisesRegex(ValueError, "exactly one"):
            shim.patch(self.root, TRUE)

    def test_changed_prologue_refused(self):
        fixture(self.root, packed=False)
        (self.root / shim.NAME).write_bytes(SOURCE.replace(b"//usr/bin/true; one", b"true; one"))
        with self.assertRaisesRegex(ValueError, "contract drift"):
            shim.patch(self.root, TRUE)


if __name__ == "__main__":
    unittest.main()
