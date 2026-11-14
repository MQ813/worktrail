"""Replaceable Markdown knowledge interface with immutable content references."""

import hashlib
import re
from pathlib import Path


class MarkdownKnowledge:
    def __init__(self, root):
        self.root = Path(root)

    def overview(self):
        return [
            dict(path=str(p.relative_to(self.root)), size=p.stat().st_size)
            for p in sorted(self.root.rglob("*.md"))
            if p.resolve().is_relative_to(self.root.resolve())
        ]

    def read(self, path):
        p = (self.root / path).resolve()
        if not p.is_relative_to(self.root.resolve()):
            raise ValueError("knowledge_path_outside_root")
        text = p.read_text(encoding="utf-8")
        return dict(
            ref=path + ":" + hashlib.sha256(text.encode()).hexdigest(),
            path=path,
            text=text,
            location="line:1",
        )

    def search(self, query, limit=3):
        words = set(re.findall(r"[\w가-힣]{2,}", query.lower()))
        ranked = []
        for entry in self.overview():
            doc = self.read(entry["path"])
            lower = doc["text"].lower()
            score = sum(min(lower.count(word), 10) for word in words)
            if score:
                ranked.append((score, doc))
        return [
            doc
            for _, doc in sorted(ranked, key=lambda item: (-item[0], item[1]["path"]))[
                :limit
            ]
        ]

    def find(self, query):
        return self.search(query)

    def related(self, path):
        return self.search(self.read(path)["text"])


def knowledge(path, body):
    return MarkdownKnowledge(path).search(body)


def refresh_freshness(db, root):
    """A KB edit invalidates a working copy even when mail has not changed."""
    import json

    adapter = MarkdownKnowledge(root)
    cache = {}
    for draft in db.execute(
        "SELECT source_id,generated FROM drafts WHERE freshness='current'"
    ).fetchall():
        for ref in json.loads(draft["generated"]).get("knowledge_refs", []):
            path = ref.rsplit(":", 1)[0]
            if path not in cache:
                try:
                    cache[path] = adapter.read(path)["ref"]
                except (OSError, ValueError):
                    cache[path] = None
            if cache[path] != ref:
                db.execute(
                    "UPDATE drafts SET freshness='stale' WHERE source_id=?",
                    (draft["source_id"],),
                )
                break
