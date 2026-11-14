"""Consistent portable backups: SQLite snapshot plus referenced immutable blobs."""

import hashlib
import json
import shutil
import sqlite3
import tempfile
from pathlib import Path

from .storage import connect


def backup(runtime, destination):
    target = Path(destination).resolve()
    if target.exists():
        raise ValueError("backup_destination_exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent, prefix=".backup-") as temp:
        root = Path(temp)
        db = connect(runtime)
        out = sqlite3.connect(root / "app.sqlite3")
        try:
            db.backup(out)
        finally:
            out.close()
            db.close()
        snap = sqlite3.connect(root / "app.sqlite3")
        refs = set()
        for raw, attachments in snap.execute(
            "SELECT raw_path,attachments FROM sources"
        ):
            refs.add(raw)
            refs.update(a["path"] for a in json.loads(attachments) if a.get("path"))
        for (snapshot,) in snap.execute("SELECT snapshot FROM revisions"):
            refs.update(
                a["path"]
                for a in json.loads(snapshot).get("attachments", [])
                if a.get("path")
            )
        # Include all immutable source blobs: revisions can refer to past JIRA raw responses.
        for p in (Path(runtime) / "blobs").glob("*"):
            if len(p.name) == 64:
                refs.add("blobs/" + p.name)
        snap.close()
        for ref in refs:
            p = Path(ref)
            if p.is_absolute() or ".." in p.parts:
                raise ValueError("invalid_blob_reference")
            dest = root / p
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(Path(runtime) / p, dest)
        project_root = Path(runtime) / "projects"
        if project_root.exists():
            for p in project_root.rglob("*"):
                if not p.is_file():
                    continue
                if not p.resolve().is_relative_to(project_root.resolve()) or p.is_symlink():
                    raise ValueError("invalid_project_document_reference")
                dest = root / p.relative_to(runtime)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(p, dest)
        manifest = {
            str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*")
            if p.is_file()
        }
        (root / "manifest.json").write_text(
            json.dumps(manifest, sort_keys=True), encoding="utf-8"
        )
        shutil.copytree(root, target)
    return str(target)


def restore(source, runtime):
    source = Path(source).resolve()
    target = Path(runtime).resolve()
    if target.exists():
        raise ValueError("restore_destination_exists")
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    if "app.sqlite3" not in manifest:
        raise ValueError("backup_database_missing")
    for ref, expected in manifest.items():
        p = (source / ref).resolve()
        if (
            not p.is_relative_to(source)
            or (source / ref).is_symlink()
            or not p.is_file()
        ):
            raise ValueError("invalid_backup_path")
        if hashlib.sha256(p.read_bytes()).hexdigest() != expected:
            raise ValueError("backup_checksum_mismatch")
    db = sqlite3.connect(source / "app.sqlite3")
    try:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("backup_integrity_failed")
        if db.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("backup_foreign_keys_failed")
    finally:
        db.close()
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent, prefix=".restore-") as temp:
        root = Path(temp) / "state"
        root.mkdir()
        for ref in manifest:
            dest = root / ref
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / ref, dest)
        db = connect(root)
        with db:
            db.execute("DELETE FROM locks")
            db.execute(
                "UPDATE jobs SET state='pending',token=NULL,lease=NULL WHERE state='running'"
            )
        db.close()
        root.rename(target)
    return str(target)
