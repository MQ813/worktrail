"""Build an offline installation directory for this OS/Python, with checksums."""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser()
p.add_argument("--output", default="dist/corporate-kit")
args = p.parse_args()
out = Path(args.output).resolve()
if out.exists():
    raise SystemExit("출력 경로가 이미 있습니다. 새 경로를 지정하세요.")
out.mkdir(parents=True)
wheels = out / "wheelhouse"
wheels.mkdir()
subprocess.run(
    [
        sys.executable,
        "-m",
        "pip",
        "wheel",
        str(root),
        "--no-deps",
        "--wheel-dir",
        str(wheels),
    ],
    check=True,
)
subprocess.run(
    [
        sys.executable,
        "-m",
        "pip",
        "download",
        "--only-binary=:all:",
        "-r",
        str(root / "requirements-test.lock"),
        "--dest",
        str(wheels),
    ],
    check=True,
)
for name in (
    "README.md",
    "pyproject.toml",
    "requirements.lock",
    "requirements-test.lock",
):
    shutil.copyfile(root / name, out / name)
for name in ("config", "docs", "tests", "scripts"):
    shutil.copytree(
        root / name, out / name, ignore=shutil.ignore_patterns("__pycache__")
    )
manifest = {
    "python": sys.version,
    "platform": sys.platform,
    "files": {
        str(f.relative_to(out)): hashlib.sha256(f.read_bytes()).hexdigest()
        for f in sorted(out.rglob("*"))
        if f.is_file()
    },
}
(out / "checksums.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(
    "준비 완료:",
    out,
    "\n이 kit은 빌드한 OS/Python용입니다. 대상 사내 환경에서 호환성을 확인하세요.",
)
