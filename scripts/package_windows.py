"""Package only the frozen application, public docs/config and integrity manifest."""

import argparse
import hashlib
import json
import shutil
import tomllib
import zipfile
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--directory", type=Path, default=Path("dist/WorkTrail"))
root = parser.parse_args().directory
version = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"][
    "version"
]
if not (root / "WorkTrail.exe").is_file():
    raise SystemExit("Build WorkTrail first")
for folder in ("docs", "config"):
    target = root / folder
    target.mkdir(exist_ok=True)
    for path in Path(folder).glob("*.md" if folder == "docs" else "*.toml"):
        shutil.copyfile(path, target / path.name)
shutil.copytree("src/mail_jira_assistant/samples", root / "samples", dirs_exist_ok=True)
(root / "WorkTrail-Samples.cmd").write_text(
    '@echo off\nstart "" "%~dp0WorkTrail.exe" --data-dir "%LOCALAPPDATA%\\WorkTrail-Samples" --samples\n',
    encoding="ascii",
)
(root / "Connect-OpenCode.cmd").write_text(
    '@echo off\n"%LOCALAPPDATA%\\Programs\\OpenCode\\bin\\opencode.exe" --standalone auth login openai --method chatgpt-headless\npause\n',
    encoding="ascii",
)
if Path("runtime/native-live-verification.json").exists():
    (root / "verification").mkdir(exist_ok=True)
    shutil.copyfile(
        "runtime/native-live-verification.json", root / "verification/native-live.json"
    )
for source, name in [
    ("runtime/project-model-evaluation.json", "project-model.json"),
    ("runtime/compact-native-smoke/verification.json", "project-native.json"),
]:
    if Path(source).exists():
        (root / "verification").mkdir(exist_ok=True)
        shutil.copyfile(source, root / "verification" / name)
ui_reports = sorted(
    Path("runtime").glob("project-review-*/verification.json"),
    key=lambda path: path.stat().st_mtime,
)
if ui_reports:
    (root / "verification").mkdir(exist_ok=True)
    shutil.copyfile(ui_reports[-1], root / "verification/project-ui.json")
shutil.copyfile("README.md", root / "README.md")
shutil.copyfile("scripts/verify_release.py", root / "verify_release.py")
shutil.copyfile("requirements-windows.lock", root / "requirements-windows.lock")
manifest = {
    str(p.relative_to(root)).replace("\\", "/"): hashlib.sha256(
        p.read_bytes()
    ).hexdigest()
    for p in root.rglob("*")
    if p.is_file() and p.name != "checksums.json"
}
(root / "checksums.json").write_text(
    json.dumps(
        {"version": version, "platform": "windows-x64", "files": manifest},
        indent=2,
        sort_keys=True,
    ),
    encoding="utf-8",
)
archive = Path(f"dist/WorkTrail-{version}-win-x64.zip")
with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as output:
    for path in root.rglob("*"):
        if path.is_file():
            output.write(
                path, "WorkTrail/" + str(path.relative_to(root)).replace("\\", "/")
            )
print(
    json.dumps(
        {
            "archive": str(archive),
            "files": len(manifest),
            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        }
    )
)
