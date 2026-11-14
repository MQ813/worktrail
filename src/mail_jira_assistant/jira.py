"""Read-only JIRA boundary. Credentials only go to the configured HTTPS origin."""

import json
import os
import re
import time
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, build_opener
from urllib.request import Request as HTTPRequest

from .documents import extract
from .service import add_revision, blob, digest, dumps
from .storage import connect


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("jira_redirect_refused")


def origin(url):
    p = urlsplit(url)
    return p.scheme, p.hostname, p.port


def register(runtime, url, servers):
    parsed = urlsplit(url)
    match = re.search(r"/browse/([A-Z][A-Z0-9_]*-\d+)", parsed.path)
    if (
        not match
        or parsed.scheme not in ("https", "http")
        or parsed.username
        or parsed.password
    ):
        raise ValueError("invalid_issue_url")
    server = next(
        (
            s
            for s in servers
            if origin(s["base_url"]) == origin(url)
            and parsed.path.startswith(
                urlsplit(s["base_url"]).path.rstrip("/") + "/browse/"
            )
        ),
        None,
    )
    key = match[1]
    server_id = (
        server["server_id"]
        if server
        else "unknown:" + parsed.scheme + "://" + parsed.netloc
    )
    iid = digest([server_id, key])
    safe_url = parsed._replace(query="", fragment="").geturl()
    db = connect(runtime)
    try:
        with db:
            db.execute(
                "INSERT INTO jira_issues(id,server_id,issue_key,url,error) VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET url=excluded.url",
                (
                    iid,
                    server_id,
                    key,
                    safe_url,
                    None if server else "connection_required",
                ),
            )
    finally:
        db.close()
    return iid


def discover(runtime, text, servers):
    result = []
    for url in re.findall(r'https?://[^\s<>"\]\)]+', text):
        if re.search(r"/browse/[A-Z][A-Z0-9_]*-\d+", url):
            result.append(register(runtime, url, servers))
    return result


class HTTPJira:
    def __init__(self, server):
        self.server = server
        self.opener = build_opener(NoRedirect())

    def request(self, path, raw=False):
        base = self.server["base_url"].rstrip("/")
        url = path if path.startswith(("https://", "http://")) else base + path
        if origin(url) != origin(base):
            raise ValueError("attachment_origin_not_allowed")
        if urlsplit(url).scheme != "https":
            raise ValueError("jira_https_required")
        headers = {"Accept": "application/json"}
        secret = self.server.get("token_env")
        if secret:
            token = os.environ.get(secret)
            if not token:
                raise ValueError("jira_credential_missing")
            if "\n" in token or "\r" in token:
                raise ValueError("invalid_credential")
            headers["Authorization"] = "Bearer " + token
        with self.opener.open(
            HTTPRequest(url, headers=headers), timeout=self.server.get("timeout", 20)
        ) as response:
            data = response.read(20 * 1024 * 1024 + 1)
        if len(data) > 20 * 1024 * 1024:
            raise ValueError("jira_response_size_limit")
        return data if raw else json.loads(data)

    def fetch(self, key):
        version = str(self.server.get("api_version", "2"))
        if version not in ("2", "3"):
            raise ValueError("unsupported_jira_api_version")
        path = "/rest/api/" + version + "/issue/" + quote(key, safe="")
        issue = self.request(path)
        comments = []
        start = 0
        for _ in range(1000):
            page = self.request(
                path + "/comment?startAt=" + str(start) + "&maxResults=100"
            )
            batch = page.get("comments", [])
            total = page.get("total")
            if total is None or page.get("startAt", start) != start:
                raise ValueError("jira_incomplete_pagination")
            comments.extend(batch)
            start += len(batch)
            if start >= total:
                break
            if not batch:
                raise ValueError("jira_incomplete_pagination")
        else:
            raise ValueError("jira_page_limit")
        issue["fields"]["comment"] = {"comments": comments, "total": len(comments)}
        return issue

    def download(self, url):
        return self.request(url, raw=True)


class FixtureJira:
    def __init__(self, server, db, issue_id):
        self.server = server
        self.db = db
        self.id = issue_id

    def fetch(self, key):
        from pathlib import Path

        path = Path(self.server["fixture"])
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and "issues" in payload:
            if key not in payload["issues"]:
                raise ValueError("fixture_issue_not_found")
            payload = payload["issues"][key]
        snapshots = payload if isinstance(payload, list) else [payload]
        row = self.db.execute(
            "SELECT value FROM meta WHERE key=?", ("fixture:" + self.id,)
        ).fetchone()
        index = int(row[0]) if row else 0
        result = snapshots[min(index, len(snapshots) - 1)]
        if "error" in result:
            raise ValueError(result["error"])
        self.db.execute(
            "INSERT OR REPLACE INTO meta VALUES(?,?)",
            ("fixture:" + self.id, str(index + 1)),
        )
        comment = result.get("fields", {}).get("comment", {})
        if comment.get("total", len(comment.get("comments", []))) != len(
            comment.get("comments", [])
        ):
            raise ValueError("jira_incomplete_pagination")
        return result

    def download(self, url):
        raise ValueError("fixture_download_unavailable")


def richtext(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if value.get("type") == "mention":
            return "@" + value.get("attrs", {}).get("id", "unknown")
        return (
            value.get("text", "")
            + "".join(richtext(c) for c in value.get("content", []))
            + ("\n" if value.get("type") in ("paragraph", "tableRow") else "")
        )
    return ""


def sync_jira(
    runtime, servers, *, history_only=True, force=False, connector_factory=None
):
    db = connect(runtime)
    count = 0
    configs = {s["server_id"]: s for s in servers}
    try:
        for tracked in db.execute(
            "SELECT * FROM jira_issues WHERE state!='paused'"
        ).fetchall():
            if not force and tracked["next_poll"] > time.time():
                continue
            server = configs.get(tracked["server_id"])
            if not server:
                continue
            try:
                connector = (
                    connector_factory(server)
                    if connector_factory
                    else (
                        FixtureJira(server, db, tracked["id"])
                        if server.get("fixture")
                        else HTTPJira(server)
                    )
                )
                issue = connector.fetch(tracked["issue_key"])
                fields = issue["fields"]
                required = {
                    "summary",
                    "description",
                    "status",
                    "comment",
                    "attachment",
                    "assignee",
                }
                if not required <= fields.keys():
                    raise ValueError("jira_incomplete_fields")
                comments = fields.get("comment", {}).get("comments", [])
                previous = (
                    json.loads(tracked["snapshot"]) if tracked["snapshot"] else None
                )
                old_attachments = {
                    a["id"]: a for a in (previous or {}).get("attachments", [])
                }
                attachments = []
                for a in fields.get("attachment", []):
                    item = dict(
                        id=str(a["id"]),
                        name=a["filename"],
                        mime=a.get("mimeType", "application/octet-stream"),
                        url=a.get("content"),
                        status="pending",
                        text="",
                    )
                    if item["id"] in old_attachments and old_attachments[item["id"]][
                        "status"
                    ] not in ("download_failed", "pending"):
                        item = old_attachments[item["id"]]
                    else:
                        try:
                            data = connector.download(a["content"])
                            item.update(
                                path=blob(runtime, data),
                                **extract(data, item["name"], item["mime"]),
                            )
                        except Exception as exc:
                            item.update(
                                status="download_failed", warnings=[type(exc).__name__]
                            )
                    attachments.append(item)
                body = richtext(fields.get("description", ""))
                for c in comments:
                    body += (
                        "\n[comment:"
                        + str(c["id"])
                        + " · "
                        + str(
                            c.get("author", {}).get(
                                "accountId", c.get("author", {}).get("name", "unknown")
                            )
                        )
                        + "]\n"
                        + richtext(c.get("body", ""))
                    )
                snapshot = dict(
                    body=body,
                    identity=server.get("identity", []),
                    subject=fields.get("summary", ""),
                    attachments=attachments,
                    status=fields.get("status", {}).get("name"),
                    assignee=fields.get("assignee"),
                    comments=[
                        {"id": str(c["id"]), "body": richtext(c.get("body", ""))}
                        for c in comments
                    ],
                )
                sid = tracked["id"]
                raw_path = blob(runtime, dumps(issue).encode())
                changed = previous != snapshot
                with db:
                    exists = db.execute(
                        "SELECT 1 FROM sources WHERE id=?", (sid,)
                    ).fetchone()
                    if not exists:
                        db.execute(
                            "INSERT INTO sources(id,message_id,conversation,subject,sender,recipients,date,body,raw_path,attachments,inquiry_id,direction,kind,baseline,coverage) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (
                                sid,
                                tracked["issue_key"],
                                sid,
                                snapshot["subject"],
                                tracked["server_id"],
                                "",
                                "",
                                body,
                                raw_path,
                                dumps(attachments),
                                sid,
                                "inbound",
                                "jira",
                                int(history_only),
                                "partial"
                                if any(a["status"] != "ready" for a in attachments)
                                else "complete",
                            ),
                        )
                        db.execute("INSERT INTO inquiries(id) VALUES(?)", (sid,))
                    elif changed:
                        db.execute(
                            "UPDATE sources SET subject=?,body=?,raw_path=?,attachments=?,baseline=?,coverage=? WHERE id=?",
                            (
                                snapshot["subject"],
                                body,
                                raw_path,
                                dumps(attachments),
                                int(history_only),
                                "partial"
                                if any(a["status"] != "ready" for a in attachments)
                                else "complete",
                                sid,
                            ),
                        )
                    if changed:
                        content_changed = previous is None or any(
                            previous.get(k) != snapshot.get(k)
                            for k in ("body", "subject", "attachments", "comments")
                        )
                        kind = (
                            "issue_created"
                            if previous is None
                            else (
                                "comments_changed"
                                if previous["comments"] != snapshot["comments"]
                                else (
                                    "issue_changed"
                                    if content_changed
                                    else "issue_metadata"
                                )
                            )
                        )
                        add_revision(
                            db, sid, sid, dict(snapshot, raw_path=raw_path), kind
                        )
                        revision = db.execute(
                            "SELECT max(id) FROM revisions WHERE inquiry_id=?", (sid,)
                        ).fetchone()[0]
                        if previous:
                            old_comments = {
                                c["id"]: c["body"] for c in previous["comments"]
                            }
                            new_comments = {
                                c["id"]: c["body"] for c in snapshot["comments"]
                            }
                            details = []
                            for cid in new_comments:
                                if cid not in old_comments:
                                    details.append(
                                        ("comment_added", {"comment_id": cid})
                                    )
                                elif old_comments[cid] != new_comments[cid]:
                                    details.append(
                                        ("comment_edited", {"comment_id": cid})
                                    )
                            for cid in old_comments.keys() - new_comments.keys():
                                details.append(("comment_deleted", {"comment_id": cid}))
                            for field in ("status", "assignee", "body"):
                                if previous.get(field) != snapshot.get(field):
                                    details.append(
                                        (
                                            field + "_changed",
                                            {
                                                "before": previous.get(field),
                                                "after": snapshot.get(field),
                                            },
                                        )
                                    )
                            for event_kind, detail in details:
                                # Multiple comments of the same kind are kept together, never discarded by uniqueness.
                                grouped = [d for k, d in details if k == event_kind]
                                db.execute(
                                    "INSERT OR IGNORE INTO events(inquiry_id,revision_id,kind,detail) VALUES(?,?,?,?)",
                                    (sid, revision, event_kind, dumps(grouped)),
                                )
                        count += 1
                    db.execute(
                        "UPDATE jira_issues SET snapshot=?,error=NULL,next_poll=? WHERE id=?",
                        (
                            dumps(snapshot),
                            time.time()
                            + (
                                server.get("closed_poll_seconds", 3600)
                                if str(snapshot.get("status", "")).lower()
                                in ("closed", "resolved", "done", "완료")
                                else server.get("poll_seconds", 300)
                            ),
                            sid,
                        ),
                    )
                db.commit()
            except Exception as exc:
                db.rollback()
                with db:
                    blocked = (
                        getattr(exc, "code", None) in (401, 403)
                        or str(exc) == "jira_credential_missing"
                    )
                    db.execute(
                        "UPDATE jira_issues SET error=?,state=?,next_poll=? WHERE id=?",
                        (
                            type(exc).__name__
                            + (
                                ":" + str(exc.code)
                                if getattr(exc, "code", None)
                                else ""
                            ),
                            "paused" if blocked else tracked["state"],
                            time.time() + 60,
                            tracked["id"],
                        ),
                    )
    finally:
        db.close()
    return count
