"""Work records reuse the existing classification transaction; no second AI pipeline."""

import hashlib
import json
import os
import tempfile
import time
from datetime import date
from pathlib import Path

from .storage import connect


def project(db, name):
    if not name or not name.strip():
        return None
    from .project_updates import ensure_project

    return ensure_project(db, name)


def capture(db, iid, revision, classification):
    """Only proposals. Source date is a suggestion, never a confirmed execution date."""
    rev = db.execute("SELECT * FROM revisions WHERE id=?", (revision,)).fetchone()
    src = db.execute("SELECT * FROM sources WHERE id=?", (rev["source_id"],)).fetchone()
    for action in classification.actions:
        if action.kind != "performed" or action.assignee != "self":
            continue
        # Reclassifying the same evidence cannot overwrite a person's edits.
        key = hashlib.sha256(
            json.dumps(
                [
                    iid,
                    rev["source_id"],
                    rev["fingerprint"],
                    sorted(action.evidence_refs),
                    action.description,
                ],
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        db.execute(
            """INSERT OR IGNORE INTO activities(inquiry_id,description,source_date,collected_at,origin_key)
                      VALUES(?,?,?,?,?)""",
            (iid, action.description, src["date"], rev["created"], key),
        )
        aid = db.execute(
            "SELECT id FROM activities WHERE origin_key=?", (key,)
        ).fetchone()[0]
        db.execute(
            "INSERT OR IGNORE INTO activity_evidence VALUES(?,?,?,?)",
            (
                aid,
                src["id"],
                revision,
                json.dumps(action.model_dump(), ensure_ascii=False),
            ),
        )
        # A proposed completion never silently closes existing tasks.


def save(runtime, data, aid=None):
    db = connect(runtime)
    try:
        with db:
            if data.get("performed_on"):
                date.fromisoformat(data["performed_on"])
            if data["status"] == "confirmed" and not data.get("performed_on"):
                raise ValueError("확정 기록에는 실제 수행일이 필요합니다.")
            old = None
            if aid:
                old = db.execute(
                    "SELECT * FROM activities WHERE id=?", (aid,)
                ).fetchone()
                if not old:
                    raise LookupError("기록 없음")
                if old["version"] != data["version"]:
                    raise ValueError("다른 창에서 변경됐습니다. 새로고침하세요.")
            iid = data.get("inquiry_id") or None
            if (
                iid
                and not db.execute(
                    "SELECT 1 FROM inquiries WHERE id=?", (iid,)
                ).fetchone()
            ):
                raise ValueError("연결할 문의를 찾을 수 없습니다.")
            action_id = data.get("action_id") or None
            if action_id:
                task = db.execute(
                    "SELECT * FROM actions WHERE id=?", (action_id,)
                ).fetchone()
                if not task or task["inquiry_id"] != iid:
                    raise ValueError("할 일과 문의 연결이 일치하지 않습니다.")
            dup = data.get("duplicate_of") or None
            if dup:
                target = db.execute(
                    "SELECT * FROM activities WHERE id=?", (dup,)
                ).fetchone()
                if not target or dup == aid or target["duplicate_of"]:
                    raise ValueError("중복 대표 기록을 확인하세요.")
                if (
                    aid
                    and db.execute(
                        "SELECT 1 FROM activities WHERE duplicate_of=?", (aid,)
                    ).fetchone()
                ):
                    raise ValueError("다른 기록의 대표는 중복 처리할 수 없습니다.")
            pid = project(db, data.get("project"))
            if not pid and iid:
                linked = db.execute(
                    "SELECT project_id FROM inquiry_projects WHERE inquiry_id=?", (iid,)
                ).fetchone()
                if not linked:
                    linked = db.execute(
                        "SELECT min(project_id) FROM project_source_links WHERE inquiry_id=? HAVING count(*)=1",
                        (iid,),
                    ).fetchone()
                pid = linked[0] if linked else None
            if data["status"] == "confirmed" and not pid:
                raise ValueError("확정 업무 기록에는 프로젝트가 필요합니다.")
            values = (
                iid,
                pid,
                action_id,
                data["description"],
                data.get("performed_on") or None,
                data["status"],
                dup,
                data.get("minutes"),
            )
            if old:
                db.execute(
                    "INSERT INTO activity_edits(activity_id,snapshot,created) VALUES(?,?,?)",
                    (aid, json.dumps(dict(old), ensure_ascii=False), time.time()),
                )
                db.execute(
                    """UPDATE activities SET inquiry_id=?,project_id=?,action_id=?,description=?,performed_on=?,status=?,duplicate_of=?,minutes=?,version=version+1 WHERE id=?""",
                    (*values, aid),
                )
            else:
                aid = db.execute(
                    """INSERT INTO activities(inquiry_id,project_id,action_id,description,performed_on,status,duplicate_of,minutes,collected_at) VALUES(?,?,?,?,?,?,?,?,?)""",
                    (*values, time.time()),
                ).lastrowid
            if data.get("complete_action"):
                if not action_id or data["status"] != "confirmed" or dup:
                    raise ValueError("확정된 대표 수행 기록과 할 일이 필요합니다.")
                db.execute(
                    "UPDATE actions SET state='done',version=version+1 WHERE id=?",
                    (action_id,),
                )
                db.execute(
                    "INSERT INTO audit(kind,target,detail,created) VALUES(?,?,?,?)",
                    ("activity_complete_action", str(action_id), str(aid), time.time()),
                )
            return aid
    finally:
        db.close()


def records(runtime):
    db = connect(runtime)
    try:
        return [
            dict(r)
            for r in db.execute("""SELECT a.*,coalesce(a.project_id,m.project_id,sl.project_id) AS resolved_project_id,coalesce(p.name,ip.name,'미지정') AS project FROM activities a
            LEFT JOIN inquiry_projects m ON m.inquiry_id=a.inquiry_id
            LEFT JOIN (SELECT inquiry_id,min(project_id) AS project_id FROM project_source_links GROUP BY inquiry_id HAVING count(*)=1) sl ON sl.inquiry_id=a.inquiry_id
            LEFT JOIN projects ip ON ip.id=coalesce(m.project_id,sl.project_id) LEFT JOIN projects p ON p.id=a.project_id
            ORDER BY a.performed_on DESC,a.id DESC""")
        ]
    finally:
        db.close()


START = "<!-- worktrail:begin -->"
END = "<!-- worktrail:end -->"


def markdown(runtime, on):
    date.fromisoformat(on)
    rows = [
        r
        for r in records(runtime)
        if r["performed_on"] == on
        and r["status"] == "confirmed"
        and not r["duplicate_of"]
    ]
    lines = [
        START,
        f"## WorkTrail · {on}",
        f"확정 수행 {len(rows)}건 (소요 시간은 직접 입력한 값만 표시)",
        "",
    ]
    for name in sorted({r["project"] for r in rows}):
        lines.append("### " + name.replace("\n", " ").replace("<!--", "&lt;!--"))
        for r in (r for r in rows if r["project"] == name):
            text = r["description"].replace("\n", " / ").replace("<!--", "&lt;!--")
            lines.append(
                f"- {text}"
                + (
                    f" ({r['minutes']}분, 수동 입력)"
                    if r["minutes"] is not None
                    else ""
                )
                + f" [기록 #{r['id']}]"
            )
        lines.append("")
    lines.append(END)
    # Filter per project inside the loop.
    return "\n".join(lines) + "\n"


def export(runtime, on, destination=None):
    path = (
        Path(destination) if destination else Path(runtime) / "exports" / (on + ".md")
    )
    generated = markdown(runtime, on)
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    if START in old or END in old:
        if (
            old.count(START) != 1
            or old.count(END) != 1
            or old.index(START) > old.index(END)
        ):
            raise ValueError(
                "생성 영역 표시가 손상되었습니다. 기존 파일을 보존했습니다."
            )
        first, tail = old.split(START)
        _, last = tail.split(END)
        text = first + generated.rstrip("\n") + last
    else:
        text = old + ("\n" if old and not old.endswith("\n") else "") + generated
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        os.replace(temp, path)
    finally:
        if Path(temp).exists():
            Path(temp).unlink()
    return path


def import_markdown(runtime, path, on, project_name=""):
    """Explicit file only. Preserve original blob; generated exports cannot feed intake."""
    from .service import blob

    path = Path(path).resolve()
    raw = path.read_bytes()
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("Markdown 2MiB 제한")
    text = raw.decode("utf-8-sig")
    if "worktrail:" in text:
        raise ValueError("WorkTrail 생성 일지는 다시 수집하지 않습니다.")
    date.fromisoformat(on)
    digest = hashlib.sha256(raw).hexdigest()
    db = connect(runtime)
    try:
        with db:
            if db.execute(
                "SELECT 1 FROM worklog_imports WHERE path=?", (str(path),)
            ).fetchone():
                raise ValueError(
                    "이미 가져온 파일입니다. 수정은 저장된 기록에서 하세요."
                )
            pid = project(db, project_name)
            original = blob(runtime, raw)
            key = "markdown:" + digest
            db.execute(
                """INSERT OR IGNORE INTO activities(description,performed_on,status,origin_key,project_id,collected_at) VALUES(?,?,'needs_review',?,?,?)""",
                (text, on, key, pid, time.time()),
            )
            db.execute(
                "INSERT INTO worklog_imports VALUES(?,?,?)",
                (str(path), digest, time.time()),
            )
            db.execute(
                "INSERT INTO audit(kind,target,detail,created) VALUES(?,?,?,?)",
                ("markdown_import", str(path), original, time.time()),
            )
    finally:
        db.close()
