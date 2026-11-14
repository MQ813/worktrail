import hashlib
import json
import time
import uuid
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses
from pathlib import Path
from threading import Event, Thread

from .contracts import Evidence, Request, validate_draft, validate_evidence
from .documents import extract, normalize_html, normalize_text
from .knowledge import MarkdownKnowledge, knowledge
from .storage import connect


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def digest(value):
    return hashlib.sha256(
        value if isinstance(value, bytes) else dumps(value).encode()
    ).hexdigest()


def audit(db, kind, target, detail):
    db.execute(
        "INSERT INTO audit(kind,target,detail,created) VALUES(?,?,?,?)",
        (kind, target, dumps(detail), time.time()),
    )


def blob(runtime, data):
    name = digest(data)
    path = Path(runtime) / "blobs" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        temp = path.with_name(name + "." + uuid.uuid4().hex + ".tmp")
        temp.write_bytes(data)
        temp.replace(path)
    return str(Path("blobs") / name)


def latest(db, iid):
    row = db.execute(
        "SELECT max(id) FROM revisions WHERE inquiry_id=?", (iid,)
    ).fetchone()
    return row[0] or 0


def add_revision(db, iid, sid, snapshot, kind="message_added"):
    fingerprint = digest(snapshot)
    cur = db.execute(
        "INSERT OR IGNORE INTO revisions(inquiry_id,source_id,fingerprint,snapshot,created) VALUES(?,?,?,?,?)",
        (iid, sid, fingerprint, dumps(snapshot), time.time()),
    )
    if cur.rowcount:
        revision = cur.lastrowid
        db.execute(
            "INSERT INTO events(inquiry_id,revision_id,kind,detail) VALUES(?,?,?,?)",
            (iid, revision, kind, dumps({"source_id": sid})),
        )
        db.execute("UPDATE drafts SET freshness='stale' WHERE source_id=?", (iid,))
        db.execute(
            "UPDATE project_changes SET freshness='stale' WHERE inquiry_id=? AND review='pending'",
            (iid,),
        )
        # Human history is retained; changed source requires renewed review.
        db.execute(
            "UPDATE inquiries SET state='needs_review' WHERE id=? AND state IN ('completed','dismissed')",
            (iid,),
        )
    return cur.rowcount


def sync(
    runtime,
    inbox,
    *,
    sent=None,
    identity=(),
    history_only=True,
    jira_servers=(),
    stable_seconds=0,
    document_adapter="eml",
    document_timeout=20,
    attachment_adapter="standard",
):
    db = connect(runtime)
    count = 0
    folders = [(Path(inbox), "inbound")] + ([(Path(sent), "outbound")] if sent else [])
    try:
        for folder, folder_direction in folders:
            paths = list(folder.rglob("*.eml"))
            if document_adapter == "outlook_msg":
                paths += list(folder.rglob("*.msg"))
            for path in sorted(paths):
                try:
                    before = path.stat()
                    if time.time() - before.st_mtime < stable_seconds:
                        continue
                    cached = db.execute(
                        "SELECT size,mtime FROM cursors WHERE path=?", (str(path),)
                    ).fetchone()
                    if cached and (cached["size"], cached["mtime"]) == (
                        before.st_size,
                        before.st_mtime_ns,
                    ):
                        continue
                    if before.st_size > 100 * 1024 * 1024:
                        raise ValueError("eml_size_limit_100MiB")
                    raw = path.read_bytes()
                    after = path.stat()
                    if (before.st_size, before.st_mtime_ns) != (
                        after.st_size,
                        after.st_mtime_ns,
                    ):
                        raise ValueError("unstable_file")
                    sid = digest(raw)
                    if db.execute(
                        "SELECT 1 FROM sources WHERE id=?", (sid,)
                    ).fetchone():
                        with db:
                            db.execute(
                                "INSERT OR REPLACE INTO cursors VALUES(?,?,?,?)",
                                (str(path), after.st_size, after.st_mtime_ns, sid),
                            )
                            db.execute(
                                "DELETE FROM sync_errors WHERE path=?", (str(path),)
                            )
                        continue
                    raw_path = blob(runtime, raw)
                    access = None
                    if document_adapter != "eml":
                        from email.message import EmailMessage

                        from .document_access import read

                        access = read(path, document_adapter, document_timeout)
                        if (
                            access["status"] not in ("ready", "partial")
                            or not access["text"].strip()
                        ):
                            raise ValueError(
                                "document_access_failed: "
                                + "; ".join(access["warnings"])
                            )
                        msg = EmailMessage()
                        for header, key in (
                            ("Subject", "subject"),
                            ("From", "sender"),
                            ("To", "recipients"),
                            ("Date", "date"),
                        ):
                            if access.get(key):
                                msg[header] = access[key]
                        msg.set_content(access["text"])
                    else:
                        msg = BytesParser(policy=policy.default).parsebytes(raw)
                    if not msg.keys() or msg.defects:
                        raise ValueError("invalid_mime")
                    body = msg.get_body(preferencelist=("plain", "html"))
                    text = body.get_content() if body else ""
                    if body and body.get_content_type() == "text/html":
                        text = normalize_html(text)
                    if not text.strip():
                        raise ValueError(
                            "empty_or_unreadable_body: 수동 원문 확인 필요"
                        )
                    text, excluded = normalize_text(text)
                    if access and access["status"] == "partial":
                        excluded["access_warnings"] = access["warnings"]
                    attachments = []
                    for part in msg.walk():
                        if part.is_multipart():
                            continue
                        if part.get_filename() or part.get("Content-ID"):
                            data = part.get_payload(decode=True) or b""
                            attachment_path = blob(runtime, data)
                            extracted = (
                                extract(
                                    data,
                                    part.get_filename(),
                                    part.get_content_type(),
                                    adapter=attachment_adapter,
                                    authorized_path=Path(runtime) / attachment_path,
                                )
                                if len(attachments) < 100
                                else dict(
                                    status="partial",
                                    text="",
                                    locations=[],
                                    warnings=["첨부 추출 개수 제한"],
                                )
                            )
                            attachments.append(
                                dict(
                                    id=digest(data),
                                    path=attachment_path,
                                    name=part.get_filename(),
                                    cid=part.get("Content-ID"),
                                    mime=part.get_content_type(),
                                    **extracted,
                                )
                            )
                    mid = str(msg.get("Message-ID", ""))
                    refs = str(
                        msg.get("References", "") or msg.get("In-Reply-To", "")
                    ).split()
                    parents = db.execute(
                        "SELECT * FROM sources WHERE message_id IN (%s) ORDER BY rowid DESC"
                        % (",".join("?" for _ in refs) or "''"),
                        refs,
                    ).fetchall()
                    parent = parents[0] if parents else None
                    conversation = (
                        parent["conversation"]
                        if parent
                        else (refs[0] if refs else (mid or sid))
                    )
                    # Identical Message-ID with different bytes is preserved for review, never silently merged.
                    collision = bool(
                        mid
                        and db.execute(
                            "SELECT 1 FROM sources WHERE message_id=?", (mid,)
                        ).fetchone()
                    )
                    existing = (
                        db.execute(
                            "SELECT inquiry_id FROM sources WHERE conversation=? LIMIT 1",
                            (conversation,),
                        ).fetchone()
                        if not collision
                        else None
                    )
                    iid = existing[0] if existing else sid
                    senders = {
                        a.lower() for _, a in getaddresses([str(msg.get("From", ""))])
                    }
                    aliases = {a.lower() for a in identity}
                    direction = (
                        ("outbound" if senders & aliases else folder_direction)
                        if aliases
                        else folder_direction
                    )
                    cc = str(msg.get("Cc", ""))
                    to = str(msg.get("To", ""))
                    if (
                        aliases
                        and folder_direction == "outbound"
                        and not senders & aliases
                    ):
                        direction = "unknown"
                    coverage = (
                        "partial"
                        if collision
                        or not text
                        or (access and access["status"] == "partial")
                        or any(a["status"] != "ready" for a in attachments)
                        else "complete"
                    )
                    from .jira import discover

                    links = discover(runtime, text, jira_servers)
                    source_kind = (
                        "jira_notification"
                        if links
                        and (
                            "jira" in str(msg.get("From", "")).lower()
                            or msg.get("Auto-Submitted")
                        )
                        else "mail"
                    )
                    if source_kind == "mail" and (
                        str(msg.get("Subject", "")).lstrip().startswith("(광고)")
                        or msg.get("List-Unsubscribe")
                        or str(msg.get("Auto-Submitted", "no")).lower()
                        not in ("no", "")
                        or str(msg.get("Precedence", "")).lower()
                        in ("bulk", "list", "junk")
                    ):
                        source_kind = "auto_notification"
                    with db:
                        db.execute(
                            "INSERT INTO sources(id,message_id,conversation,subject,sender,recipients,date,body,raw_path,attachments,inquiry_id,direction,kind,baseline,coverage) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (
                                sid,
                                mid,
                                conversation,
                                str(msg.get("Subject", "(제목 없음)")),
                                str(msg.get("From", "")),
                                to + "; CC: " + cc,
                                str(msg.get("Date", "")),
                                text,
                                raw_path,
                                dumps(attachments),
                                iid,
                                direction,
                                source_kind,
                                int(history_only),
                                coverage,
                            ),
                        )
                        if iid == sid:
                            db.execute("INSERT INTO inquiries(id) VALUES(?)", (iid,))
                        add_revision(
                            db,
                            iid,
                            sid,
                            dict(
                                body=text,
                                excluded=excluded,
                                subject=str(msg.get("Subject", "(제목 없음)")),
                                attachments=attachments,
                                source_id=sid,
                                direction=direction,
                                to=to,
                                cc=cc,
                                identity=list(identity),
                                message_id_collision=collision,
                            ),
                        )
                        from .rules import non_action

                        ruled = non_action(
                            str(msg.get("Subject", "")),
                            text,
                            source_kind,
                            to,
                            cc,
                            identity,
                        )
                        if ruled and iid == sid:
                            rule_id, result = ruled
                            result.evidence = [
                                Evidence(
                                    source_ref=iid, segment_ref="body", text=text[:160]
                                )
                            ]
                            db.execute(
                                "INSERT OR REPLACE INTO classifications VALUES(?,?)",
                                (iid, result.model_dump_json()),
                            )
                            db.execute(
                                "INSERT INTO classification_history(inquiry_id,revision_id,result,created) VALUES(?,?,?,?)",
                                (
                                    iid,
                                    latest(db, iid),
                                    result.model_dump_json(),
                                    time.time(),
                                ),
                            )
                            db.execute(
                                "UPDATE inquiries SET state='dismissed' WHERE id=?",
                                (iid,),
                            )
                            audit(db, "classification_rule", iid, {"rule_id": rule_id})
                        db.execute(
                            "INSERT OR REPLACE INTO cursors VALUES(?,?,?,?)",
                            (str(path), after.st_size, after.st_mtime_ns, sid),
                        )
                        db.execute("DELETE FROM sync_errors WHERE path=?", (str(path),))
                    count += 1
                except Exception as exc:
                    with db:
                        db.execute(
                            "INSERT OR REPLACE INTO sync_errors VALUES(?,?)",
                            (str(path), type(exc).__name__ + ": " + str(exc)),
                        )
        with db:
            db.execute(
                "INSERT OR REPLACE INTO meta VALUES(?,?)",
                ("last_mail_sync", str(time.time())),
            )
    finally:
        db.close()
    return count


def queue_job(db, iid, kind, revision):
    db.execute(
        "INSERT OR IGNORE INTO jobs(source_id,kind,input_version) VALUES(?,?,?)",
        (iid, kind, revision),
    )


def enqueue(runtime, sid=None, *, include_history=True, regenerate=False):
    db = connect(runtime)
    try:
        with db:
            if sid:
                source = db.execute(
                    "SELECT inquiry_id FROM sources WHERE id=?", (sid,)
                ).fetchone()
                ids = [source[0]] if source else []
            else:
                ids = [
                    r[0]
                    for r in db.execute(
                        "SELECT DISTINCT inquiry_id FROM sources WHERE kind NOT IN ('jira_notification','auto_notification')"
                        + ("" if include_history else " AND baseline=0")
                    )
                ]
            for iid in ids:
                revision = latest(db, iid)
                if (
                    not sid
                    and db.execute(
                        "SELECT 1 FROM audit WHERE kind='classification_rule' AND target=?",
                        (iid,),
                    ).fetchone()
                    and db.execute(
                        "SELECT 1 FROM classification_history WHERE inquiry_id=? AND revision_id=?",
                        (iid, revision),
                    ).fetchone()
                ):
                    continue
                if not include_history:
                    last = db.execute(
                        "SELECT s.baseline,s.kind FROM revisions r JOIN sources s ON s.id=r.source_id WHERE r.id=?",
                        (revision,),
                    ).fetchone()
                    if last and (
                        last["baseline"]
                        or last["kind"] in ("jira_notification", "auto_notification")
                    ):
                        continue
                    if db.execute(
                        "SELECT 1 FROM events WHERE revision_id=? AND kind='issue_metadata'",
                        (revision,),
                    ).fetchone():
                        continue
                kind = "draft" if regenerate else "classify"
                if sid:
                    request_id = uuid.uuid4().hex
                    db.execute(
                        "INSERT INTO jobs(source_id,kind,input_version,request_id) VALUES(?,?,?,?)",
                        (iid, kind, revision, request_id),
                    )
                    audit(
                        db,
                        "job_requested",
                        iid,
                        {"request_id": request_id, "kind": kind, "revision": revision},
                    )
                else:
                    queue_job(db, iid, kind, revision)
    finally:
        db.close()


def build_request(db, iid, revision, kb, kind, max_chars):
    source = db.execute("SELECT * FROM sources WHERE id=?", (iid,)).fetchone()
    revs = db.execute(
        "SELECT r.*,s.direction,s.coverage FROM revisions r JOIN sources s ON s.id=r.source_id WHERE r.inquiry_id=? AND s.inquiry_id=r.inquiry_id AND r.id<=? ORDER BY r.id DESC",
        (iid, revision),
    ).fetchall()
    if not revs:
        return Request(
            source_ref=iid,
            subject=source["subject"],
            body=source["body"],
            knowledge=knowledge(kb, source["body"]) if kind == "draft" else [],
            context_version=revision,
        )
    current = json.loads(revs[0]["snapshot"])
    limitations = []
    if revs[0]["coverage"] != "complete":
        limitations.append("원문 또는 첨부 해석이 불완전합니다. 확인 전 확정 답변 금지")
    if current.get("message_id_collision"):
        limitations.append("Message-ID 충돌: 연결 확인 필요")
    body = current.get("body", "")
    for attachment in current.get("attachments", []):
        body += (
            "\n[첨부 "
            + str(attachment.get("name"))
            + " · "
            + attachment["status"]
            + "]\n"
            + attachment.get("text", "")
        )
    # Reserve newest question before adding bounded history and KB. Never silently truncate newest source.
    if len(body) > max_chars // 2:
        raise ValueError("input_budget_exceeded")
    for old in revs[1:10]:
        historical = json.loads(old["snapshot"])
        text = historical.get("body", "")
        for attachment in historical.get("attachments", []):
            text += (
                "\n[첨부 "
                + str(attachment.get("name"))
                + " · "
                + attachment["status"]
                + "]\n"
                + attachment.get("text", "")
            )
            if (
                attachment["status"] != "ready"
                and "미해석 첨부가 이전 대화에 있습니다" not in limitations
            ):
                limitations.append("미해석 첨부가 이전 대화에 있습니다")
        if len(body) + len(text) > max_chars // 2:
            limitations.append("과거 대화 일부 제외: 입력 예산")
            break
        body += "\n[이전 대화]\n" + text
    docs = knowledge(kb, current.get("body", "")) if kind == "draft" else []
    kept = []
    for doc in docs:
        if len(dumps(kept)) + len(dumps(doc)) + len(body) > max_chars - 3000:
            limitations.append("지식 문서 일부 제외: 입력 예산")
            continue
        kept.append(doc)
    if kind == "draft" and not kept:
        limitations.append("적용 가능한 지식 근거 없음: 내부 확인 필요")
    notes = [
        dict(r)
        for r in db.execute(
            "SELECT state,note,revision_id FROM overrides WHERE inquiry_id=? AND revision_id<=? ORDER BY id DESC LIMIT 5",
            (iid, revision),
        )
    ]
    classified = db.execute(
        "SELECT result FROM classifications WHERE source_id=?", (iid,)
    ).fetchone()
    missing = (
        json.loads(classified[0]).get("missing_information", [])
        if classified and kind == "draft"
        else []
    )
    manual = db.execute(
        "SELECT result,note,revision_id FROM manual_classifications WHERE inquiry_id=? AND revision_id<=? ORDER BY id DESC LIMIT 1",
        (iid, revision),
    ).fetchone()
    if manual:
        notes.append(
            {
                "manual_classification": json.loads(manual["result"]),
                "note": manual["note"],
                "revision_id": manual["revision_id"],
            }
        )
    return Request(
        source_ref=iid,
        subject=current.get("subject", source["subject"]),
        body=body,
        knowledge=kept,
        limitations=limitations,
        direction=revs[0]["direction"],
        identity=current.get("identity", []),
        context_version=revision,
        recipients=current.get("to", ""),
        cc=current.get("cc", ""),
        notes=notes,
        missing_information=missing,
        open_actions=[
            dict(r)
            for r in db.execute(
                "SELECT id,description,assignee,due_at,state FROM actions WHERE inquiry_id=? AND state IN ('open','proposed','waiting')",
                (iid,),
            )
        ],
    )


def acquire_lock(db, name, token, lease=90):
    now = time.time()
    with db:
        db.execute(
            "INSERT OR IGNORE INTO locks VALUES(?,?,?)", (name, token, now + lease)
        )
        return bool(
            db.execute(
                "UPDATE locks SET token=?,expires=? WHERE name=? AND (token=? OR expires<?)",
                (token, now + lease, name, token, now),
            ).rowcount
        )


def worker(
    runtime,
    runner,
    kb,
    max_chars=24000,
    *,
    lease_seconds=90,
    retry_delay=30,
    automatic_drafts=True,
    automatic_project_updates=True,
):
    db = connect(runtime)
    done = 0
    owner = uuid.uuid4().hex
    if not acquire_lock(db, "worker", owner, lease_seconds):
        db.close()
        return 0
    if automatic_project_updates:
        from .contracts import Classification
        from .project_updates import schedule

        with db:
            for (
                ruled
            ) in db.execute("""SELECT c.source_id,c.result FROM classifications c
                JOIN sources s ON s.id=c.source_id WHERE s.baseline=0
                AND EXISTS(SELECT 1 FROM audit a WHERE a.kind='classification_rule' AND a.target=c.source_id)""").fetchall():
                schedule(
                    db,
                    ruled["source_id"],
                    latest(db, ruled["source_id"]),
                    Classification.model_validate_json(ruled["result"]),
                )
    stop = Event()
    active = {"token": None, "job": None}

    def heartbeat():
        while not stop.wait(max(0.1, lease_seconds / 3)):
            heart = connect(runtime)
            try:
                with heart:
                    owned = heart.execute(
                        "UPDATE locks SET expires=? WHERE name=? AND token=?",
                        (time.time() + lease_seconds, "worker", owner),
                    ).rowcount
                    if owned and active["token"]:
                        heart.execute(
                            "UPDATE jobs SET lease=? WHERE id=? AND token=? AND state='running'",
                            (
                                time.time() + lease_seconds,
                                active["job"],
                                active["token"],
                            ),
                        )
            finally:
                heart.close()

    thread = Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        while True:
            now = time.time()
            token = uuid.uuid4().hex
            db.execute("BEGIN IMMEDIATE")
            if not db.execute(
                "SELECT 1 FROM locks WHERE name=? AND token=? AND expires>?",
                ("worker", owner, time.time()),
            ).fetchone():
                db.commit()
                break
            db.execute(
                "UPDATE attempts SET error='lease_expired',finished=? WHERE finished IS NULL AND job_id IN (SELECT id FROM jobs WHERE state='running' AND lease<?)",
                (now, now),
            )
            db.execute(
                "UPDATE jobs SET state=CASE WHEN attempts>=3 THEN 'failed' ELSE 'pending' END,token=NULL,error='lease_expired' WHERE state='running' AND lease<?",
                (now,),
            )
            row = db.execute(
                "SELECT * FROM jobs WHERE state IN ('pending','retry_wait') AND available<=? ORDER BY id LIMIT 1",
                (now,),
            ).fetchone()
            if not row:
                db.commit()
                break
            db.execute(
                "UPDATE jobs SET state='running',attempts=attempts+1,token=?,lease=? WHERE id=?",
                (token, now + lease_seconds, row["id"]),
            )
            attempt = db.execute(
                "INSERT INTO attempts(job_id,token,started) VALUES(?,?,?)",
                (row["id"], token, now),
            ).lastrowid
            db.commit()
            active.update(token=token, job=row["id"])
            try:
                revision = row["input_version"] or latest(db, row["source_id"])
                request = build_request(
                    db, row["source_id"], revision, kb, row["kind"], max_chars
                )
                if row["kind"] == "classify":
                    request.projects = [
                        dict(p)
                        for p in db.execute(
                            "SELECT id,code,name,purpose FROM projects ORDER BY id LIMIT 100"
                        )
                    ]
                if row["kind"] == "project_update":
                    from .project_updates import context

                    request.projects = context(db, row["source_id"])
                    if row["request_id"].startswith("history:"):
                        request.history_basis = latest(db, row["source_id"])
                        target = int(row["request_id"].split(":")[1])
                        request.projects = [
                            p for p in request.projects if p["id"] == target
                        ]
                    if not request.projects:
                        raise ValueError("프로젝트 연결이 필요합니다.")
                with db:
                    db.execute(
                        "UPDATE attempts SET input=? WHERE id=?",
                        (request.model_dump_json(), attempt),
                    )
                if len(request.model_dump_json()) > max_chars:
                    raise ValueError("input_budget_exceeded")
                if row["kind"] == "classify":
                    result = runner.classify(request)
                    validate_evidence(result, request)
                elif row["kind"] == "draft":
                    result = runner.draft(request)
                    validate_draft(result, request)
                elif row["kind"] == "project_update":
                    from .contracts import validate_project_update

                    result = runner.project_update(request)
                    validate_project_update(result, request)
                else:
                    raise ValueError("unknown_job_kind")
                db.execute("BEGIN IMMEDIATE")
                owned = db.execute(
                    "SELECT 1 FROM locks WHERE name=? AND token=? AND expires>?",
                    ("worker", owner, time.time()),
                ).fetchone()
                changed = (
                    db.execute(
                        "UPDATE jobs SET state='succeeded',error=NULL WHERE id=? AND token=? AND state='running' AND lease>?",
                        (row["id"], token, time.time()),
                    ).rowcount
                    if owned
                    else 0
                )
                if not changed:
                    db.execute(
                        "UPDATE attempts SET error=?,finished=? WHERE id=?",
                        ("late_result_discarded", time.time(), attempt),
                    )
                    db.commit()
                    continue
                iid = row["source_id"]
                current = latest(db, iid)
                freshness = "current" if current == revision else "stale"
                for doc in request.knowledge:
                    try:
                        current_ref = MarkdownKnowledge(kb).read(doc["path"])["ref"]
                    except (OSError, ValueError):
                        current_ref = None
                    if doc["ref"] != current_ref:
                        freshness = "stale"
                if row["kind"] == "classify":
                    db.execute(
                        "INSERT INTO classification_history(inquiry_id,revision_id,result,created) VALUES(?,?,?,?)",
                        (iid, revision, result.model_dump_json(), time.time()),
                    )
                    if current == revision:
                        db.execute(
                            "INSERT OR REPLACE INTO classifications VALUES(?,?)",
                            (iid, result.model_dump_json()),
                        )
                        from .worklog import capture

                        capture(db, iid, revision, result)
                        if automatic_project_updates:
                            from .project_updates import schedule

                            schedule(db, iid, revision, result)
                        for action in result.actions:
                            db.execute(
                                "INSERT OR IGNORE INTO actions(inquiry_id,description,assignee,due_at,state,evidence) VALUES(?,?,?,?,?,?)",
                                (
                                    iid,
                                    action.description,
                                    action.assignee,
                                    action.due_at,
                                    "proposed",
                                    dumps(
                                        dict(
                                            kind=action.kind,
                                            refs=action.evidence_refs,
                                            related_action_ids=action.related_action_ids,
                                            revision=revision,
                                        )
                                    ),
                                ),
                            )
                        correction = db.execute(
                            "SELECT result FROM manual_classifications WHERE inquiry_id=? AND revision_id=? ORDER BY id DESC LIMIT 1",
                            (iid, revision),
                        ).fetchone()
                        expected = (
                            json.loads(correction[0])["response_expected"]
                            if correction
                            else result.response_expected
                        )
                        dismissed = db.execute(
                            "SELECT 1 FROM overrides WHERE inquiry_id=? AND revision_id=? AND state IN ('completed','dismissed') ORDER BY id DESC LIMIT 1",
                            (iid, revision),
                        ).fetchone()
                        if (
                            automatic_drafts
                            and not dismissed
                            and expected == "yes"
                            and request.direction != "outbound"
                        ):
                            queue_job(db, iid, "draft", revision)
                elif row["kind"] == "project_update":
                    from .project_updates import store

                    store(db, request, result)
                elif row["kind"] == "draft":
                    db.execute(
                        "INSERT INTO draft_versions(inquiry_id,revision_id,generated,created) VALUES(?,?,?,?)",
                        (iid, revision, result.model_dump_json(), time.time()),
                    )
                    existing = db.execute(
                        "SELECT * FROM drafts WHERE source_id=?", (iid,)
                    ).fetchone()
                    if not existing:
                        db.execute(
                            "INSERT INTO drafts(source_id,generated,body,revision_id,freshness,context_hash) VALUES(?,?,?,?,?,?)",
                            (
                                iid,
                                result.model_dump_json(),
                                result.body,
                                revision,
                                freshness,
                                digest(request.model_dump()),
                            ),
                        )
                    elif existing["review"] == "generated":
                        db.execute(
                            "UPDATE drafts SET generated=?,body=?,version=version+1,revision_id=?,freshness=?,context_hash=? WHERE source_id=?",
                            (
                                result.model_dump_json(),
                                result.body,
                                revision,
                                freshness,
                                digest(request.model_dump()),
                                iid,
                            ),
                        )
                    else:
                        # Regeneration is a candidate; reviewed/edited working copy is never overwritten.
                        db.execute(
                            "UPDATE drafts SET freshness=CASE WHEN revision_id=? THEN freshness ELSE 'stale' END WHERE source_id=?",
                            (current, iid),
                        )
                if current != revision and request.history_basis is None:
                    eligible = db.execute(
                        "SELECT s.baseline FROM revisions r JOIN sources s ON s.id=r.source_id WHERE r.id=?",
                        (current,),
                    ).fetchone()
                    if eligible and not eligible[0]:
                        queue_job(db, iid, "classify", current)
                db.execute(
                    "UPDATE attempts SET runner_log=? WHERE id=?",
                    (dumps(getattr(runner, "last_log", {})), attempt),
                )
                db.execute(
                    "UPDATE attempts SET output=?,finished=? WHERE id=?",
                    (result.model_dump_json(), time.time(), attempt),
                )
                db.commit()
                done += 1
            except Exception as exc:
                db.rollback()
                error = type(exc).__name__ + ": " + str(exc)
                from pydantic import ValidationError

                transient = (
                    isinstance(
                        exc,
                        (
                            TimeoutError,
                            ConnectionError,
                            json.JSONDecodeError,
                            ValidationError,
                        ),
                    )
                    or str(exc).startswith("empty_output")
                    or (
                        isinstance(exc, RuntimeError)
                        and str(exc) in ("timeout", "nonzero_exit")
                    )
                )
                state = (
                    "retry_wait" if transient and row["attempts"] + 1 < 3 else "failed"
                )
                with db:
                    db.execute(
                        "UPDATE jobs SET state=?,error=?,available=? WHERE id=? AND token=? AND state='running'",
                        (
                            state,
                            error,
                            time.time() + retry_delay if state == "retry_wait" else 0,
                            row["id"],
                            token,
                        ),
                    )
                    db.execute(
                        "UPDATE attempts SET error=?,finished=?,runner_log=? WHERE id=?",
                        (
                            error,
                            time.time(),
                            dumps(getattr(runner, "last_log", {})),
                            attempt,
                        ),
                    )
            finally:
                active.update(token=None, job=None)
    finally:
        stop.set()
        thread.join(timeout=5)
        with db:
            db.execute("DELETE FROM locks WHERE name=? AND token=?", ("worker", owner))
        db.close()
    return done


def poll(runtime, inbox, *, activate=False, **kwargs):
    db = connect(runtime)
    owner = uuid.uuid4().hex
    if not acquire_lock(db, "poll", owner, 90):
        db.close()
        return 0
    stop = Event()

    def heartbeat():
        while not stop.wait(20):
            heart = connect(runtime)
            try:
                with heart:
                    heart.execute(
                        "UPDATE locks SET expires=? WHERE name=? AND token=?",
                        (time.time() + 90, "poll", owner),
                    )
            finally:
                heart.close()

    thread = Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        count = sync(runtime, inbox, history_only=not activate, **kwargs)
        servers = kwargs.get("jira_servers", ())
        if servers:
            from .jira import sync_jira

            count += sync_jira(runtime, servers, history_only=not activate)
        if activate:
            enqueue(runtime, include_history=False)
        return count
    finally:
        stop.set()
        thread.join(timeout=5)
        with db:
            db.execute("DELETE FROM locks WHERE name=? AND token=?", ("poll", owner))
        db.close()


def preview(runtime, inbox, *, sent=None, activate=False):
    import sqlite3

    path = Path(runtime) / "app.sqlite3"
    db = (
        sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        if path.exists()
        else None
    )
    result = []
    try:
        for folder in [inbox, sent]:
            if not folder:
                continue
            for file in sorted(Path(folder).rglob("*.eml")):
                try:
                    sid = digest(file.read_bytes())
                    exists = (
                        db.execute(
                            "SELECT kind,baseline FROM sources WHERE id=?", (sid,)
                        ).fetchone()
                        if db
                        else None
                    )
                    result.append(
                        {
                            "path": str(file),
                            "event": "unchanged" if exists else "message_added",
                            "rule": "already_collected"
                            if exists
                            else ("new_change" if activate else "history_baseline"),
                            "planned_job": "classify"
                            if activate and not exists
                            else None,
                        }
                    )
                except OSError as exc:
                    result.append({"path": str(file), "error": type(exc).__name__})
    finally:
        if db:
            db.close()
    return {
        "files": result,
        "jira": "dry-run은 네트워크를 조회하지 않습니다. 원격 변경은 실제 수집에서 확인합니다.",
    }
