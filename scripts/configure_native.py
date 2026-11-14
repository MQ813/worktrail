"""Native OpenCode configuration for this Windows user; stores no credentials."""

import argparse
import json
import os
import shutil
from datetime import datetime
from pathlib import Path

from mail_jira_assistant.operations import backup
from mail_jira_assistant.sample_data import install, prepare
from mail_jira_assistant.settings import load


def configure(root, samples=True):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    exe = Path(os.environ["LOCALAPPDATA"]) / "Programs/OpenCode/bin/opencode.exe"
    if not exe.is_file():
        raise ValueError("Native OpenCode is not installed")
    config = root / "settings.toml"
    settings = load(config) if config.exists() else load()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if config.exists():
        shutil.copyfile(config, root / f"settings-before-native-{stamp}.toml")
    if (root / "runtime/app.sqlite3").exists():
        backup(root / "runtime", root / f"backup-before-native-{stamp}")
    changes = dict(
        profile="home",
        runtime=str(root / "runtime"),
        ai_backend="opencode",
        ai_executable=str(exe),
        ai_prefix=[],
        ai_global_args=["--standalone"],
        ai_input="stdin",
        classify_model="openai/gpt-6.1-sol-fast",
        draft_model="openai/gpt-6.1-sol-fast",
        ai_timeout=120,
        automatic_drafts=True,
        history_only=True,
    )
    if samples:
        sample = prepare(root)
        changes.update(
            sample_mode=True, inbox=sample["inbox"], knowledge=sample["knowledge"]
        )
        changes["identity"] = list(
            dict.fromkeys(settings.identity + sample["identity"])
        )
        changes["jira_servers"] = [
            s for s in settings.jira_servers if s["server_id"] != "worktrail-samples"
        ] + sample["jira_servers"]
    for key, value in changes.items():
        setattr(settings, key, value)
    data = settings.model_dump()
    servers = data.pop("jira_servers")
    text = (
        "\n".join(
            f"{key} = {str(value).lower() if isinstance(value, bool) else json.dumps(value, ensure_ascii=False)}"
            for key, value in data.items()
            if value is not None
        )
        + "\n"
    )
    for server in servers:
        text += (
            "\n[[jira_servers]]\n"
            + "\n".join(
                f"{key} = {str(value).lower() if isinstance(value, bool) else json.dumps(value, ensure_ascii=False)}"
                for key, value in server.items()
            )
            + "\n"
        )
    config.write_text(text, encoding="utf-8")
    settings = load(config)
    if samples:
        install(settings.runtime, settings)
    print(
        json.dumps(
            dict(config=str(config), native_executable=str(exe), samples=samples),
            ensure_ascii=True,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data-dir", type=Path, default=Path(os.environ["LOCALAPPDATA"]) / "WorkTrail"
    )
    parser.add_argument("--no-samples", action="store_true")
    args = parser.parse_args()
    configure(args.data_dir, not args.no_samples)
