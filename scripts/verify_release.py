"""Verify release checksums using only the Python standard library."""

import argparse
import hashlib
import json
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("directory", nargs="?", default=str(Path(__file__).resolve().parents[1]))
args = p.parse_args()
root = Path(args.directory).resolve()
manifest = json.loads((root / "checksums.json").read_text(encoding="utf-8"))
for name, expected in manifest["files"].items():
    path = (root / name).resolve()
    if (
        not path.is_relative_to(root)
        or (root / name).is_symlink()
        or not path.is_file()
    ):
        raise SystemExit("잘못된 파일: " + name)
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise SystemExit("체크섬 불일치: " + name)
print("Checksum verification passed:", len(manifest["files"]), "files")
