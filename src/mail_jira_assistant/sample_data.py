"""Install the explicitly requested synthetic pack without replacing existing files."""

import json
import shutil
from pathlib import Path


def prepare(root):
    root = Path(root)
    pack = Path(__file__).parent / "samples"
    manifest = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
    targets = {
        "inbox": root / "inbox" / "worktrail-samples-v1",
        "knowledge": root / "knowledge" / "worktrail-samples-v1",
        "jira": root / "jira" / "worktrail-samples-v1",
    }
    for source, dest in targets.items():
        dest.mkdir(parents=True, exist_ok=True)
        for path in (pack / source).iterdir():
            target = dest / path.name
            if not target.exists():
                shutil.copyfile(path, target)
    return dict(
        inbox=str(root / "inbox"),
        knowledge=str(root / "knowledge"),
        identity=manifest["identity"],
        jira_servers=[
            dict(
                server_id="worktrail-samples",
                base_url="https://jira.worktrail.example",
                fixture=str(targets["jira"] / "issues.json"),
                poll_seconds=60,
                identity=["mingyu.cho", "조민규"],
            )
        ],
    )


def install(runtime, settings):
    from .jira import sync_jira
    from .service import enqueue, sync

    sync(
        runtime,
        settings.inbox,
        identity=settings.identity,
        jira_servers=settings.jira_servers,
        history_only=False,
    )
    sync_jira(runtime, settings.jira_servers, history_only=False, force=True)
    enqueue(runtime)
