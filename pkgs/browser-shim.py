"""Repair and inspect the browser shim in either reviewed upstream layout."""

import hashlib
import json
from pathlib import Path
import struct
import sys


NAME = "claude-browser-shim.js"


def locate(resources):
    archive = resources / "app.asar"
    data = archive.read_bytes()
    _, header_size, _, json_size = struct.unpack_from("<4I", data)
    header = json.loads(data[16:16 + json_size])
    payload = 8 + header_size
    if not 16 + json_size <= payload <= len(data):
        raise ValueError("Invalid ASAR header")
    entry = header["files"].get("resources", {}).get("files", {}).get(NAME)
    loose = resources / NAME
    if loose.is_file() == (entry is not None):
        raise ValueError("Expected exactly one browser shim in a reviewed location")
    if entry is None:
        return loose.read_bytes(), None
    if entry.get("unpacked") or "offset" not in entry or not entry.get("executable"):
        raise ValueError("Expected a packed executable browser shim")
    start = payload + int(entry["offset"])
    end = start + entry["size"]
    if not payload <= start <= end <= len(data):
        raise ValueError("Invalid browser shim bounds")
    source = data[start:end]
    integrity = entry["integrity"]
    block_size = integrity["blockSize"]
    if (integrity["algorithm"] != "SHA256" or block_size <= 0
            or integrity["hash"] != hashlib.sha256(source).hexdigest()
            or integrity["blocks"] != [hashlib.sha256(source[i:i + block_size]).hexdigest()
                                       for i in range(0, len(source), block_size)]):
        raise ValueError("Browser shim integrity mismatch")
    return source, (archive, data, header, payload, entry)


def patch(resources, true_path):
    source, packed = locate(resources)
    if (not true_path.startswith("/nix/store/") or not true_path.endswith("/bin/true")
            or not source.startswith(b"#!/bin/sh\n")
            or source.count(b"//usr/bin/true;") != 3):
        raise ValueError("Browser shim prologue contract drift")
    source = source.replace(b"//usr/bin/true;", b"/" + true_path.encode() + b";")
    if packed is None:
        (resources / NAME).write_bytes(source)
        return
    archive, data, header, payload, entry = packed
    entry["offset"] = str(len(data) - payload)
    entry["size"] = len(source)
    block_size = entry["integrity"]["blockSize"]
    entry["integrity"].update(
        hash=hashlib.sha256(source).hexdigest(),
        blocks=[hashlib.sha256(source[i:i + block_size]).hexdigest()
                for i in range(0, len(source), block_size)],
    )
    encoded = json.dumps(header, separators=(",", ":"), ensure_ascii=False).encode()
    padded = encoded + b"\0" * (-len(encoded) % 4)
    archive.write_bytes(struct.pack("<4I", 4, len(padded) + 8, len(padded) + 4, len(encoded))
                        + padded + data[payload:] + source)


if __name__ == "__main__":
    mode, directory, target = sys.argv[1:]
    resources = Path(directory)
    if mode == "patch":
        patch(resources, target)
    elif mode == "extract":
        output = Path(target)
        output.write_bytes(locate(resources)[0])
        output.chmod(0o755)
    else:
        raise ValueError("Expected patch or extract")
