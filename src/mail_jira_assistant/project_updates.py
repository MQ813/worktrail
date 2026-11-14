"""Project documents: confirmed entries plus independently reviewable AI changes."""

import hashlib
import json
import re
import time
import uuid
from pathlib import Path

from .storage import connect

SECTIONS = {
    "overview": "개요",
    "progress": "현재 진행 항목",
    "issues": "주요 이슈",
    "decisions": "주요 결정",
    "updates": "최근 업데이트",
    "next_actions": "다음 액션",
}


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def migrate(db, script, column):
    for name, definition in [
        ("code", "TEXT"),
        ("purpose", "TEXT DEFAULT ''"),
        ("owner", "TEXT DEFAULT ''"),
        ("state", "TEXT DEFAULT 'active'"),
        ("started_on", "TEXT DEFAULT ''"),
        ("version", "INTEGER NOT NULL DEFAULT 1"),
    ]:
        column(db, "projects", name, definition)
    db.execute("UPDATE projects SET code=printf('JOB-%03d',id) WHERE code IS NULL")
    script("""
    CREATE UNIQUE INDEX IF NOT EXISTS projects_code ON projects(code);
    CREATE TABLE IF NOT EXISTS project_work_items(id INTEGER PRIMARY KEY,project_id INTEGER NOT NULL REFERENCES projects(id),title TEXT NOT NULL,detail INTEGER DEFAULT 0,UNIQUE(project_id,title));
    CREATE TABLE IF NOT EXISTS project_source_links(inquiry_id TEXT REFERENCES inquiries(id),project_id INTEGER REFERENCES projects(id),origin TEXT NOT NULL,PRIMARY KEY(inquiry_id,project_id));
    CREATE TABLE IF NOT EXISTS project_entries(id INTEGER PRIMARY KEY,project_id INTEGER NOT NULL REFERENCES projects(id),work_item_id INTEGER REFERENCES project_work_items(id),section TEXT NOT NULL,kind TEXT NOT NULL,text TEXT NOT NULL,action_id INTEGER REFERENCES actions(id),version INTEGER NOT NULL DEFAULT 1,deleted INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS project_update_runs(id INTEGER PRIMARY KEY,inquiry_id TEXT,revision_id INTEGER,context TEXT,result TEXT,created REAL);
    CREATE TABLE IF NOT EXISTS project_changes(id INTEGER PRIMARY KEY,run_id INTEGER REFERENCES project_update_runs(id),project_id INTEGER REFERENCES projects(id),inquiry_id TEXT,revision_id INTEGER,base_version INTEGER,entry_id INTEGER REFERENCES project_entries(id),payload TEXT NOT NULL,before_text TEXT,review TEXT NOT NULL DEFAULT 'pending',freshness TEXT NOT NULL DEFAULT 'current',dedup TEXT NOT NULL UNIQUE,created REAL);
    CREATE TABLE IF NOT EXISTS project_reviews(id INTEGER PRIMARY KEY,change_id INTEGER REFERENCES project_changes(id),decision TEXT,payload TEXT,actor TEXT NOT NULL DEFAULT 'local_user',created REAL);
    CREATE TABLE IF NOT EXISTS project_unassigned(inquiry_id TEXT PRIMARY KEY,revision_id INTEGER,hints TEXT NOT NULL DEFAULT '[]');
    CREATE TABLE IF NOT EXISTS project_documents(project_id INTEGER REFERENCES projects(id),path TEXT,hash TEXT,PRIMARY KEY(project_id,path));
    CREATE TABLE IF NOT EXISTS project_imports(project_id INTEGER REFERENCES projects(id),path TEXT,hash TEXT,blob TEXT,PRIMARY KEY(project_id,path));
    """)
    db.execute(
        "INSERT OR IGNORE INTO project_source_links SELECT inquiry_id,project_id,'user' FROM inquiry_projects WHERE project_id IS NOT NULL"
    )


def ensure_project(db, name, code=None):
    if not name.strip():
        raise ValueError("프로젝트 이름을 입력하세요.")
    if code and not re.fullmatch(r"JOB-\d{3,}", code):
        raise ValueError("프로젝트 코드는 JOB-001 형식이어야 합니다.")
    db.execute("INSERT OR IGNORE INTO projects(name) VALUES(?)", (name.strip(),))
    row = db.execute("SELECT * FROM projects WHERE name=?", (name.strip(),)).fetchone()
    if code and row["code"] and code != row["code"]:
        raise ValueError("기존 프로젝트 코드와 다릅니다.")
    if row["code"] is None:
        candidate = code or f"JOB-{row['id']:03d}"
        while db.execute(
            "SELECT 1 FROM projects WHERE code=?", (candidate,)
        ).fetchone():
            candidate = f"JOB-{int(candidate[4:]) + 1:03d}"
            if code:
                raise ValueError("이미 사용 중인 프로젝트 코드입니다.")
        db.execute("UPDATE projects SET code=? WHERE id=?", (candidate, row["id"]))
    return row["id"]


def context(db, iid):
    result = []
    for row in db.execute(
        """SELECT DISTINCT p.* FROM projects p WHERE p.id IN
        (SELECT project_id FROM project_source_links WHERE inquiry_id=? UNION
         SELECT project_id FROM inquiry_projects WHERE inquiry_id=?) ORDER BY p.id""",
        (iid, iid),
    ):
        p = dict(row)
        p["entries"] = [
            dict(r)
            for r in db.execute(
                "SELECT * FROM project_entries WHERE project_id=? AND deleted=0",
                (p["id"],),
            )
        ]
        p["work_items"] = [
            dict(r)
            for r in db.execute(
                "SELECT * FROM project_work_items WHERE project_id=?", (p["id"],)
            )
        ]
        p["pending"] = [
            dict(r)
            for r in db.execute(
                "SELECT id,payload,review FROM project_changes WHERE project_id=? AND review IN ('pending','rejected') ORDER BY id DESC LIMIT 50",
                (p["id"],),
            )
        ]
        result.append(p)
    return result


def schedule(db, iid, revision, classification=None, force=False):
    from .service import queue_job

    if classification and classification.project_update_needed == "no":
        return False
    if not context(db, iid):
        hints = classification.project_hints if classification else []
        source = db.execute(
            "SELECT subject,body FROM sources WHERE id=?", (iid,)
        ).fetchone()
        explicit = set(
            re.findall(r"\bJOB-\d{3,}\b", " ".join([source["subject"], source["body"]]))
        )
        if len(explicit) == 1:
            row = db.execute(
                "SELECT id FROM projects WHERE code=?", (next(iter(explicit)),)
            ).fetchone()
            if (
                row
                and not db.execute(
                    "SELECT 1 FROM audit WHERE kind='project_unlink' AND target=? AND detail=?",
                    (iid, str(row[0])),
                ).fetchone()
            ):
                db.execute(
                    "INSERT OR IGNORE INTO project_source_links VALUES(?,?,'code')",
                    (iid, row[0]),
                )
        if not context(db, iid):
            db.execute(
                "INSERT OR REPLACE INTO project_unassigned VALUES(?,?,?)",
                (iid, revision, encoded(hints)),
            )
            return False
    db.execute("DELETE FROM project_unassigned WHERE inquiry_id=?", (iid,))
    if force:
        db.execute(
            "INSERT INTO jobs(source_id,kind,input_version,request_id) VALUES(?,'project_update',?,?)",
            (iid, revision, uuid.uuid4().hex),
        )
    else:
        queue_job(db, iid, "project_update", revision)
    return True


def store(db, request, result):
    from .service import latest

    run = db.execute(
        "INSERT INTO project_update_runs(inquiry_id,revision_id,context,result,created) VALUES(?,?,?,?,?)",
        (
            request.source_ref,
            request.context_version,
            encoded(request.projects),
            result.model_dump_json(),
            time.time(),
        ),
    ).lastrowid
    for change in result.changes:
        p = next(p for p in request.projects if p["id"] == change.project_id)
        entry = next((e for e in p["entries"] if e["id"] == change.entry_id), None)
        if change.metadata_field and p[change.metadata_field] == change.text:
            continue
        if change.operation == "add" and any(
            e["section"] == change.section and e["text"] == change.text
            for e in p["entries"]
        ):
            continue
        if entry and change.operation == "update" and entry["text"] == change.text:
            continue

        def comparable(value):
            return {
                k: v
                for k, v in value.items()
                if k not in ("reason", "evidence", "_history_basis")
            }

        previous = [
            dict(r)
            for r in db.execute(
                "SELECT * FROM project_changes WHERE inquiry_id=? AND revision_id=? AND project_id=?",
                (request.source_ref, request.context_version, p["id"]),
            )
        ]
        identical = [
            c
            for c in previous
            if comparable(json.loads(c["payload"])) == comparable(change.model_dump())
        ]
        if any(
            c["review"] in ("rejected", "confirmed")
            or (
                c["review"] == "pending"
                and c["freshness"] == "current"
                and c["base_version"] == p["version"]
            )
            for c in identical
        ):
            continue
        for old in identical:
            if old["review"] == "pending":
                db.execute(
                    "UPDATE project_changes SET review='superseded' WHERE id=?",
                    (old["id"],),
                )
        if change.entry_id:
            db.execute(
                "UPDATE project_changes SET review='superseded' WHERE inquiry_id=? AND project_id=? AND entry_id=? AND revision_id<? AND review='pending' AND freshness='stale'",
                (request.source_ref, p["id"], change.entry_id, request.context_version),
            )
        # Rebased proposals keep their old versions as superseded history.
        key = hashlib.sha256(
            encoded(
                [
                    request.source_ref,
                    request.context_version,
                    p["version"],
                    change.model_dump(),
                    run if identical else 0,
                ]
            ).encode()
        ).hexdigest()
        current = db.execute(
            "SELECT version FROM projects WHERE id=?", (p["id"],)
        ).fetchone()
        fresh = (
            "current"
            if current
            and current[0] == p["version"]
            and latest(db, request.source_ref)
            == (request.history_basis or request.context_version)
            else "stale"
        )
        if fresh == "current" and (change.entry_id or change.metadata_field):
            # Keep contradictory alternatives visible rather than choosing by arrival order.
            alternatives = db.execute(
                "SELECT id,entry_id,payload FROM project_changes WHERE project_id=? AND review='pending' AND freshness='current' AND dedup<>?",
                (p["id"], key),
            ).fetchall()
            alternatives = [
                a
                for a in alternatives
                if (change.entry_id and a["entry_id"] == change.entry_id)
                or (
                    change.metadata_field
                    and json.loads(a["payload"]).get("metadata_field")
                    == change.metadata_field
                )
            ]
            if alternatives:
                fresh = "conflict"
                db.executemany(
                    "UPDATE project_changes SET freshness='conflict' WHERE id=?",
                    [(r[0],) for r in alternatives],
                )
        payload = change.model_dump()
        if request.history_basis is not None:
            payload["_history_basis"] = request.history_basis
        db.execute(
            """INSERT OR IGNORE INTO project_changes(run_id,project_id,inquiry_id,revision_id,base_version,entry_id,payload,before_text,freshness,dedup,created)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                run,
                p["id"],
                request.source_ref,
                request.context_version,
                p["version"],
                change.entry_id,
                encoded(payload),
                p[change.metadata_field]
                if change.metadata_field
                else entry["text"]
                if entry
                else "",
                fresh,
                key,
                time.time(),
            ),
        )


def link(runtime, iid, name):
    from .service import latest

    db = connect(runtime)
    try:
        with db:
            if not db.execute("SELECT 1 FROM inquiries WHERE id=?", (iid,)).fetchone():
                raise ValueError("문의 없음")
            pid = ensure_project(db, name)
            db.execute(
                "INSERT OR REPLACE INTO project_source_links VALUES(?,?,'user')",
                (iid, pid),
            )
            db.execute(
                "INSERT OR REPLACE INTO inquiry_projects VALUES(?,?)", (iid, pid)
            )
            schedule(db, iid, latest(db, iid), force=True)
            return pid
    finally:
        db.close()


def unlink(runtime, iid, pid):
    db = connect(runtime)
    try:
        with db:
            db.execute(
                "DELETE FROM project_source_links WHERE inquiry_id=? AND project_id=?",
                (iid, pid),
            )
            db.execute(
                "DELETE FROM inquiry_projects WHERE inquiry_id=? AND project_id=?",
                (iid, pid),
            )
            db.execute(
                "UPDATE project_changes SET freshness='stale' WHERE inquiry_id=? AND project_id=? AND review='pending'",
                (iid, pid),
            )
            db.execute(
                "INSERT INTO audit(kind,target,detail,created) VALUES('project_unlink',?,?,?)",
                (iid, str(pid), time.time()),
            )
    finally:
        db.close()


def review(runtime, selections):
    """Validate every selection first; one conflict rolls back the whole batch."""
    from .service import latest

    db = connect(runtime)
    try:
        db.execute("BEGIN IMMEDIATE")
        rows = []
        targets = set()
        if not selections or len({s["id"] for s in selections}) != len(selections):
            raise ValueError("검토할 변경을 선택하세요. 중복 선택은 허용되지 않습니다.")
        for selection in selections:
            row = db.execute(
                "SELECT * FROM project_changes WHERE id=?", (selection["id"],)
            ).fetchone()
            if not row or row["review"] != "pending":
                raise ValueError("이미 처리되었거나 존재하지 않는 변경입니다.")
            p = db.execute(
                "SELECT version FROM projects WHERE id=?", (row["project_id"],)
            ).fetchone()
            if selection["decision"] == "confirmed":
                payload = json.loads(row["payload"])
                target = payload.get("entry_id") or payload.get("metadata_field")
                if target:
                    key = (row["project_id"], str(target))
                    if key in targets:
                        raise ValueError(
                            "같은 항목의 상충 변경은 한 번에 확정할 수 없습니다."
                        )
                    targets.add(key)
                if (
                    row["base_version"] != p[0]
                    or row["freshness"] != "current"
                    or (
                        row["inquiry_id"]
                        and latest(db, row["inquiry_id"])
                        != json.loads(row["payload"]).get(
                            "_history_basis", row["revision_id"]
                        )
                    )
                ):
                    raise ValueError(
                        "재검토가 필요합니다. 최신 원문과 프로젝트로 다시 생성하세요."
                    )
                if (
                    row["inquiry_id"]
                    and not db.execute(
                        "SELECT 1 FROM project_source_links WHERE inquiry_id=? AND project_id=? UNION SELECT 1 FROM inquiry_projects WHERE inquiry_id=? AND project_id=?",
                        (
                            row["inquiry_id"],
                            row["project_id"],
                            row["inquiry_id"],
                            row["project_id"],
                        ),
                    ).fetchone()
                ):
                    raise ValueError("프로젝트 연결이 변경되었습니다.")
            rows.append((selection, row))
        touched = set()
        for selection, row in rows:
            payload = json.loads(row["payload"])
            text = (
                selection.get("text")
                if selection.get("text") is not None
                else payload["text"]
            )
            if not text.strip() or len(text) > 5000:
                raise ValueError("변경 내용은 1~5000자여야 합니다.")
            if selection["decision"] == "confirmed":
                if payload.get("metadata_field"):
                    field = payload["metadata_field"]
                    if field not in ("purpose", "owner", "state", "started_on"):
                        raise ValueError("허용되지 않은 개요 항목")
                    if field == "started_on":
                        from datetime import date

                        date.fromisoformat(text)
                    db.execute(
                        f"UPDATE projects SET {field}=? WHERE id=?",
                        (text, row["project_id"]),
                    )
                wid = payload.get("work_item_id")
                if not wid and payload.get("work_title"):
                    db.execute(
                        "INSERT INTO project_work_items(project_id,title,detail) VALUES(?,?,?) ON CONFLICT(project_id,title) DO UPDATE SET detail=max(detail,excluded.detail)",
                        (
                            row["project_id"],
                            payload["work_title"],
                            int(payload.get("detail", False)),
                        ),
                    )
                    wid = db.execute(
                        "SELECT id FROM project_work_items WHERE project_id=? AND title=?",
                        (row["project_id"], payload["work_title"]),
                    ).fetchone()[0]
                if payload["operation"] == "add":
                    eid = db.execute(
                        "INSERT INTO project_entries(project_id,work_item_id,section,kind,text,action_id) VALUES(?,?,?,?,?,?)",
                        (
                            row["project_id"],
                            wid,
                            payload["section"],
                            payload["kind"],
                            text,
                            payload.get("action_id"),
                        ),
                    ).lastrowid
                else:
                    eid = payload["entry_id"]
                    db.execute(
                        "UPDATE project_entries SET text=?,deleted=?,version=version+1 WHERE id=? AND project_id=?",
                        (
                            text,
                            int(payload["operation"] == "delete"),
                            eid,
                            row["project_id"],
                        ),
                    )
                if payload.get("action_id") and payload["kind"] in ("todo", "waiting"):
                    db.execute(
                        "UPDATE actions SET state=?,version=version+1 WHERE id=? AND state='proposed'",
                        (
                            "waiting" if payload["kind"] == "waiting" else "open",
                            payload["action_id"],
                        ),
                    )
                # A project update never marks performed activities/actions complete implicitly.
                touched.add(row["project_id"])
            db.execute(
                "UPDATE project_changes SET review=? WHERE id=?",
                (selection["decision"], row["id"]),
            )
            db.execute(
                "INSERT INTO project_reviews(change_id,decision,payload,created) VALUES(?,?,?,?)",
                (
                    row["id"],
                    selection["decision"],
                    encoded({"original": payload, "text": text}),
                    time.time(),
                ),
            )
        for pid in touched:
            db.execute("UPDATE projects SET version=version+1 WHERE id=?", (pid,))
            db.execute(
                "UPDATE project_changes SET freshness='stale' WHERE project_id=? AND review='pending'",
                (pid,),
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def refresh_imports(db, pid):
    p = db.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
    if not p:
        raise ValueError("프로젝트 없음")
    changed = 0
    for old in db.execute(
        "SELECT * FROM project_changes WHERE project_id=? AND inquiry_id IS NULL AND review='pending' AND base_version<>?",
        (pid, p["version"]),
    ).fetchall():
        if not db.execute(
            "UPDATE project_changes SET review='superseded' WHERE id=? AND review='pending'",
            (old["id"],),
        ).rowcount:
            continue
        payload = json.loads(old["payload"])
        before = (
            p[payload["metadata_field"]]
            if payload.get("metadata_field")
            else old["before_text"]
        )
        db.execute(
            "INSERT INTO project_changes(run_id,project_id,base_version,entry_id,payload,before_text,dedup,created) VALUES(?,?,?,?,?,?,?,?)",
            (
                old["run_id"],
                pid,
                p["version"],
                old["entry_id"],
                old["payload"],
                before,
                f"import-rebase:{old['id']}:{p['version']}",
                time.time(),
            ),
        )
        changed += 1
    return changed


def replay_history(runtime, pid, start, end):
    from datetime import date, datetime, timedelta
    from datetime import time as day_time
    from zoneinfo import ZoneInfo

    start_date, end_date = date.fromisoformat(start), date.fromisoformat(end)
    if end_date < start_date:
        raise ValueError("종료일은 시작일 이후여야 합니다.")
    zone = ZoneInfo("Asia/Seoul")
    first = datetime.combine(start_date, day_time.min, zone).timestamp()
    last = datetime.combine(
        end_date + timedelta(days=1), day_time.min, zone
    ).timestamp()
    db = connect(runtime)
    try:
        with db:
            revisions = db.execute(
                """SELECT r.id,r.inquiry_id FROM revisions r WHERE r.created>=? AND r.created<?
                AND r.inquiry_id IN (SELECT inquiry_id FROM project_source_links WHERE project_id=? UNION SELECT inquiry_id FROM inquiry_projects WHERE project_id=?)
                AND NOT EXISTS(SELECT 1 FROM sources s WHERE s.id=r.source_id AND s.kind='jira_notification') ORDER BY r.id LIMIT 501""",
                (first, last, pid, pid),
            ).fetchall()
            if len(revisions) > 500:
                raise ValueError("수집 이력 500건 이하로 기간을 좁혀주세요.")
            for rev in revisions:
                db.execute(
                    "INSERT INTO jobs(source_id,kind,input_version,request_id) VALUES(?,'project_update',?,?)",
                    (
                        rev["inquiry_id"],
                        rev["id"],
                        f"history:{pid}:" + uuid.uuid4().hex,
                    ),
                )
            db.execute(
                "INSERT INTO audit(kind,target,detail,created) VALUES('project_history_replay',?,?,?)",
                (
                    str(pid),
                    encoded({"start": start, "end": end, "count": len(revisions)}),
                    time.time(),
                ),
            )
            return len(revisions)
    finally:
        db.close()


def import_document(runtime, pid, path):
    """Explicit external edit intake. Original is immutable; changes remain pending."""
    from .service import blob
    from .worklog import END, START

    path = Path(path).resolve()
    if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("가져올 Markdown은 2MiB 이하여야 합니다.")
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig")
    if START in text or END in text:
        if (
            text.count(START) != 1
            or text.count(END) != 1
            or text.index(START) > text.index(END)
        ):
            raise ValueError("생성 영역 표시가 손상되었습니다.")
        text = text.split(START)[1].split(END)[0]
    db = connect(runtime)
    try:
        with db:
            p = db.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
            if not p:
                raise ValueError("프로젝트 없음")
            original = blob(runtime, raw)
            run = db.execute(
                "INSERT INTO project_update_runs(context,result,created) VALUES(?,?,?)",
                (encoded(dict(p)), "{}", time.time()),
            ).lastrowid
            section = "updates"
            known = {
                r[0]
                for r in db.execute(
                    "SELECT text FROM project_entries WHERE project_id=? AND deleted=0",
                    (pid,),
                )
            }
            for number, line in enumerate(text.splitlines()):
                if line.startswith("## "):
                    if line[3:].strip() == "AI 변경 · 미확정":
                        break
                    section = next(
                        (
                            k
                            for k, title in SECTIONS.items()
                            if title == line[3:].strip()
                        ),
                        "updates",
                    )
                    continue
                if not line.startswith("- "):
                    continue
                value = line[2:].strip()
                if value in {
                    v.strip()
                    for v in {
                        f"목적: {p['purpose']}",
                        f"담당자: {p['owner']}",
                        f"상태: {p['state']}",
                        f"시작일: {p['started_on']}",
                    }
                }:
                    continue
                if not value or value in known or len(value) > 5000:
                    continue
                payload = {
                    "project_id": pid,
                    "section": section,
                    "kind": "progress",
                    "operation": "add",
                    "text": value,
                    "reason": "외부 수정 문서에서 가져온 추가 후보. 기존 항목의 삭제·대체는 직접 확인하세요.",
                    "evidence": [
                        {"source_ref": original, "segment_ref": str(path), "text": line}
                    ],
                }
                key = hashlib.sha256(
                    encoded([pid, original, number]).encode()
                ).hexdigest()
                db.execute(
                    "INSERT OR IGNORE INTO project_changes(run_id,project_id,base_version,payload,before_text,dedup,created) VALUES(?,?,?,?,?,?,?)",
                    (run, pid, p["version"], encoded(payload), "", key, time.time()),
                )
            db.execute(
                "INSERT OR REPLACE INTO project_imports VALUES(?,?,?,?)",
                (
                    pid,
                    "external/" + path.name,
                    hashlib.sha256(raw).hexdigest(),
                    original,
                ),
            )
            # Record the exact acknowledged generated region; human memo outside stays untouched.
            root = (Path(runtime) / "projects").resolve()
            if path.is_relative_to(root) and START in raw.decode("utf-8-sig"):
                block = (
                    raw.decode("utf-8-sig")
                    .replace("\r\n", "\n")
                    .split(START)[1]
                    .split(END)[0]
                )
                db.execute(
                    "INSERT OR REPLACE INTO project_documents VALUES(?,?,?)",
                    (
                        pid,
                        path.relative_to(root).as_posix(),
                        hashlib.sha256(block.encode()).hexdigest(),
                    ),
                )
    finally:
        db.close()


def edit_project(runtime, pid, data):
    from datetime import date

    if data.get("started_on"):
        date.fromisoformat(data["started_on"])
    db = connect(runtime)
    try:
        with db:
            changed = db.execute(
                "UPDATE projects SET purpose=?,owner=?,state=?,started_on=?,version=version+1 WHERE id=? AND version=?",
                (
                    data["purpose"],
                    data["owner"],
                    data["state"],
                    data["started_on"],
                    pid,
                    data["version"],
                ),
            ).rowcount
            if not changed:
                raise ValueError("다른 변경이 있습니다. 새로고침하세요.")
            db.execute(
                "UPDATE project_changes SET freshness='stale' WHERE project_id=? AND review='pending'",
                (pid,),
            )
            db.execute(
                "INSERT INTO audit(kind,target,detail,created) VALUES('project_edit',?,?,?)",
                (str(pid), encoded(data), time.time()),
            )
    finally:
        db.close()


def markdown(db, pid, pending=True, wid=None):
    p = db.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
    if not p:
        raise ValueError("프로젝트 없음")
    lines = [f"# {p['code']} {p['name']}", ""]
    entries = [
        dict(r)
        for r in db.execute(
            "SELECT * FROM project_entries WHERE project_id=? AND deleted=0 ORDER BY id",
            (pid,),
        )
    ]
    for section, title in SECTIONS.items():
        lines.extend(["## " + title, ""])
        if section == "overview":
            lines.extend(
                [
                    f"- 목적: {p['purpose']}",
                    f"- 담당자: {p['owner']}",
                    f"- 상태: {p['state']}",
                    f"- 시작일: {p['started_on']}",
                ]
            )
        if section == "progress" and wid is None:
            lines.extend(
                ["| 구분 | 상태 | 다음 작업 | 문서 |", "| --- | --- | --- | --- |"]
            )
            for w in db.execute(
                "SELECT * FROM project_work_items WHERE project_id=?", (pid,)
            ):
                title = w["title"].replace("|", "\\|").replace("\n", " ")
                doc = f"[상세](issues/ISSUE-{w['id']:03d}.md)" if w["detail"] else ""
                state = " / ".join(
                    e["text"]
                    for e in entries
                    if e["work_item_id"] == w["id"] and e["section"] == "progress"
                )
                action = " / ".join(
                    e["text"]
                    for e in entries
                    if e["work_item_id"] == w["id"] and e["section"] == "next_actions"
                )
                state = state.replace("|", "\\|").replace("\n", " ")
                action = action.replace("|", "\\|").replace("\n", " ")
                lines.append(f"| {title} | {state} | {action} | {doc} |")
        lines.extend(
            "- " + e["text"].replace("\n", "\n  ")
            for e in entries
            if e["section"] == section and (wid is None or e["work_item_id"] == wid)
        )
        lines.append("")
    if wid is None:
        for a in db.execute(
            """SELECT DISTINCT a.* FROM activities a LEFT JOIN inquiry_projects ip ON ip.inquiry_id=a.inquiry_id
                WHERE coalesce(a.project_id,ip.project_id)=? AND a.status='confirmed' AND a.duplicate_of IS NULL""",
            (pid,),
        ):
            lines.append(f"- 수행 {a['performed_on']}: {a['description']}")
    if pending:
        lines.extend(["", "## AI 변경 · 미확정", ""])
        for c in db.execute(
            "SELECT * FROM project_changes WHERE project_id=? AND review='pending' ORDER BY id",
            (pid,),
        ):
            data = json.loads(c["payload"])
            if wid is not None and data.get("work_item_id") != wid:
                continue
            lines.append(
                f"- [미확정 #{c['id']} / {c['freshness']}] {data['operation']}: {data['text']}"
            )
            if c["before_text"]:
                lines.append("  - 기존: " + c["before_text"])
            lines.append(
                f"  - 근거: inquiry={c['inquiry_id']}, revision={c['revision_id']}"
            )
            for evidence in data["evidence"]:
                lines.append("  - 발췌: " + evidence["text"].replace("\n", " / "))
    return "\n".join(lines) + "\n"


def export(runtime, pid, destination=None, pending=True):
    from .worklog import END, START

    db = connect(runtime)
    try:
        p = db.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
        if not p:
            raise ValueError("프로젝트 없음")
        root = Path(destination) if destination else Path(runtime) / "projects"
        folder = root / p["code"]
        documents = {"index.md": markdown(db, pid, pending)}
        for w in db.execute(
            "SELECT * FROM project_work_items WHERE project_id=? AND detail=1", (pid,)
        ):
            documents[f"issues/ISSUE-{w['id']:03d}.md"] = markdown(
                db, pid, pending, w["id"]
            )
        # Preflight every document before mutating any files.
        rendered = {}
        for relative, content in documents.items():
            path = folder / relative
            old = path.read_text(encoding="utf-8") if path.exists() else ""
            saved = db.execute(
                "SELECT hash FROM project_documents WHERE project_id=? AND path=?",
                (pid, path.relative_to(root).as_posix()),
            ).fetchone()
            if old:
                if (
                    old.count(START) != 1
                    or old.count(END) != 1
                    or old.index(START) > old.index(END)
                ):
                    raise ValueError(
                        "기존 문서의 생성 영역을 확인하세요. 파일을 보존했습니다."
                    )
                before, rest = old.split(START)
                generated, after = rest.split(END)
                if (
                    not saved
                    or hashlib.sha256(generated.encode()).hexdigest() != saved[0]
                ):
                    raise ValueError(
                        "외부에서 생성 영역을 수정했습니다. 가져오기 후 다시 내보내세요."
                    )
            else:
                before = after = ""
            block = "\n" + content + "\n"
            rendered[path] = (
                before + START + block + END + after,
                hashlib.sha256(block.encode()).hexdigest(),
            )
        with db:
            for path, (content, digest) in rendered.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                temp = path.with_suffix(".tmp")
                temp.write_text(content, encoding="utf-8", newline="\n")
                temp.replace(path)
                db.execute(
                    "INSERT OR REPLACE INTO project_documents VALUES(?,?,?)",
                    (pid, path.relative_to(root).as_posix(), digest),
                )
        assets = {}
        for imported in db.execute(
            "SELECT * FROM project_imports WHERE project_id=? AND path LIKE 'assets/%'",
            (pid,),
        ):
            assets[imported["path"]] = imported["blob"]
        for source in db.execute(
            "SELECT attachments FROM sources WHERE inquiry_id IN (SELECT inquiry_id FROM project_source_links WHERE project_id=? UNION SELECT inquiry_id FROM inquiry_projects WHERE project_id=?)",
            (pid, pid),
        ):
            for attachment in json.loads(source[0]):
                if attachment.get("path"):
                    name = re.sub(
                        r"[^\w.\-가-힣]", "_", attachment.get("name", "attachment")
                    )[:100]
                    assets[
                        "assets/" + Path(attachment["path"]).name[:12] + "_" + name
                    ] = attachment["path"]
        for relative, ref in assets.items():
            target = (folder / relative).resolve()
            original = (Path(runtime) / ref).resolve()
            if not target.is_relative_to(
                folder.resolve()
            ) or not original.is_relative_to((Path(runtime) / "blobs").resolve()):
                raise ValueError("invalid_asset_path")
            raw = original.read_bytes()
            if target.exists() and target.read_bytes() != raw:
                raise ValueError("첨부 파일이 외부에서 변경되었습니다. 보존했습니다.")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        return folder / "index.md"
    finally:
        db.close()


def import_folder(runtime, folder):
    from .service import blob

    folder = Path(folder).resolve()
    if (
        not re.fullmatch(r"JOB-\d{3,}", folder.name)
        or not (folder / "index.md").is_file()
    ):
        raise ValueError("index.md가 있는 JOB-001 형식의 폴더를 지정하세요.")
    paths = [folder / "index.md"]
    for sub in ("issues", "assets"):
        if (folder / sub).exists():
            paths.extend(p for p in (folder / sub).rglob("*") if p.is_file())
    if len(paths) > 500:
        raise ValueError("프로젝트 파일 500개 제한")
    contents = {}
    total = 0
    for path in paths:
        if folder not in path.resolve().parents:
            raise ValueError("폴더 외부 링크는 가져올 수 없습니다.")
        if path.stat().st_size > 20 * 1024 * 1024:
            raise ValueError("파일 20MiB 제한")
        raw = path.read_bytes()
        total += len(raw)
        if total > 100 * 1024 * 1024:
            raise ValueError("프로젝트 100MiB 제한")
        contents[path] = raw
    index = contents[folder / "index.md"].decode("utf-8-sig")
    if "worktrail:" in index:
        raise ValueError("생성 문서는 새 프로젝트로 재입력할 수 없습니다.")
    name = (
        re.sub(
            r"^#\s*JOB-\d+\s*", "", index.splitlines()[0] if index.splitlines() else ""
        ).strip()
        or folder.name
    )
    db = connect(runtime)
    try:
        with db:
            pid = ensure_project(db, name, folder.name)
            run = db.execute(
                "INSERT INTO project_update_runs(context,result,created) VALUES('[]','{}',?)",
                (time.time(),),
            ).lastrowid
            for path, raw in contents.items():
                relative = path.relative_to(folder).as_posix()
                digest = hashlib.sha256(raw).hexdigest()
                original = blob(runtime, raw)
                db.execute(
                    "INSERT OR REPLACE INTO project_imports VALUES(?,?,?,?)",
                    (pid, relative, digest, original),
                )
                if path.suffix.lower() != ".md":
                    continue
                text = raw.decode("utf-8-sig")
                if "worktrail:" in text:
                    raise ValueError("생성 문서 재입력 금지")
                section = "updates"
                chunks = []
                for line in text.splitlines(keepends=True):
                    if line.startswith("## "):
                        section = next(
                            (
                                k
                                for k, title in SECTIONS.items()
                                if line[3:].strip() == title
                            ),
                            "updates",
                        )
                        continue
                    if line.startswith("# ") or not line.strip():
                        continue
                    for offset in range(0, len(line), 4500):
                        chunks.append((section, line[offset : offset + 4500].strip()))
                for number, (section, excerpt) in enumerate(chunks):
                    if not excerpt:
                        continue
                    payload = {
                        "project_id": pid,
                        "section": section,
                        "kind": "decision"
                        if section == "decisions"
                        else "todo"
                        if section == "next_actions"
                        else "progress",
                        "operation": "add",
                        "text": excerpt,
                        "work_title": path.stem
                        if relative.startswith("issues/")
                        else "",
                        "detail": relative.startswith("issues/"),
                        "reason": "기존 문서 가져오기: " + relative,
                        "evidence": [
                            {
                                "source_ref": original,
                                "segment_ref": relative,
                                "text": excerpt,
                            }
                        ],
                    }
                    if section == "overview":
                        for label, field in (
                            ("목적", "purpose"),
                            ("담당자", "owner"),
                            ("상태", "state"),
                            ("시작일", "started_on"),
                        ):
                            match = re.match(
                                r"^-?\s*" + label + r"\s*:\s*(.*)$", excerpt
                            )
                            if match:
                                payload["metadata_field"] = field
                                payload["text"] = match[1].strip()
                                payload["kind"] = "project_metadata"
                                break
                    if not payload["text"]:
                        continue
                    key = hashlib.sha256(
                        encoded([pid, relative, digest, number]).encode()
                    ).hexdigest()
                    db.execute(
                        "INSERT OR IGNORE INTO project_changes(run_id,project_id,base_version,payload,before_text,dedup,created) VALUES(?,?,?,?,?,?,?)",
                        (
                            run,
                            pid,
                            db.execute(
                                "SELECT version FROM projects WHERE id=?", (pid,)
                            ).fetchone()[0],
                            encoded(payload),
                            "",
                            key,
                            time.time(),
                        ),
                    )
            return pid
    finally:
        db.close()
