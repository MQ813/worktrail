"""Coverage and grounding limits (S01–02,11–13,18–19)."""

import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient
from test_tracking import mail

from mail_jira_assistant.ai import FakeRunner
from mail_jira_assistant.contracts import Draft, Request, validate_draft
from mail_jira_assistant.documents import extract, normalize_html
from mail_jira_assistant.knowledge import MarkdownKnowledge
from mail_jira_assistant.service import enqueue, sync, worker
from mail_jira_assistant.storage import connect
from mail_jira_assistant.web import create_app


def archive(files):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
    return out.getvalue()


def test_html_table_links_and_inline_images_preserved_without_active_content():
    result = normalize_html(
        '<style>tracking{}</style><script>bad()</script><table><tr><th>조건</th><th>전류</th></tr><tr><td>125℃</td><td>10uA</td></tr></table><a href="https://jira.test/browse/A-1">이슈</a><img src="cid:circuit">'
    )
    assert "tracking" not in result and "bad()" not in result
    assert "조건 | 전류" in result and "125℃ | 10uA" in result
    assert "https://jira.test/browse/A-1" in result and "cid:circuit" in result


def test_text_csv_office_and_broken_attachment_locations():
    assert "row:2" in extract(b"a,b\n1,2", "data.csv", "text/csv")["text"]
    assert (
        extract(b"bad", "broken.docx", "application/octet-stream")["status"]
        == "extract_failed"
    )
    doc = archive(
        {
            "word/document.xml": '<w:document xmlns:w="word"><w:p><w:t>Voltage condition</w:t></w:p></w:document>'
        }
    )
    d = extract(doc, "conditions.docx", "application/octet-stream")
    assert (
        d["status"] == "ready"
        and "word/document.xml" in d["locations"]
        and "Voltage condition" in d["text"]
    )
    ppt = archive(
        {
            "ppt/slides/slide1.xml": '<a:sld xmlns:a="drawing"><a:t>Review conditions</a:t></a:sld>'
        }
    )
    assert (
        "slide1.xml" in extract(ppt, "slides.pptx", "application/octet-stream")["text"]
    )
    xlsx = archive(
        {
            "xl/sharedStrings.xml": "<sst><si><t>GPIO</t></si></sst>",
            "xl/worksheets/sheet1.xml": '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row><c r="A1" t="s"><v>0</v></c><c r="B1"><f>1+2</f><v>3</v></c></row></sheetData></worksheet>',
        }
    )
    x = extract(xlsx, "cells.xlsx", "application/octet-stream")
    assert (
        "A1: GPIO" in x["text"] and "B1: 3" in x["text"] and "재계산 안 함" in x["text"]
    )
    assert extract(b"image", "circuit.png", "image/png")["status"] == "needs_vision"
    assert (
        extract(b"\0", "file.bin", "application/octet-stream")["status"]
        == "unsupported"
    )


def test_scanned_and_invalid_pdf_do_not_fabricate_text():
    from pypdf import PdfWriter

    out = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(out)
    assert (
        extract(out.getvalue(), "scan.pdf", "application/pdf")["status"]
        == "needs_vision"
    )
    assert (
        extract(b"not a pdf", "broken.pdf", "application/pdf")["status"]
        == "extract_failed"
    )


def test_kb_interfaces_versions_paths_and_applicability(tmp_path):
    (tmp_path / "gpio.md").write_text(
        "# GPIO\nOnly process A at 25C.\nLeakage is 10uA."
    )
    kb = MarkdownKnowledge(tmp_path)
    doc = kb.search("GPIO process A")[0]
    assert len(kb.overview()) == 1 and kb.find("GPIO") and kb.related("gpio.md")
    with pytest.raises(ValueError):
        kb.read("../secret")
    request = Request(
        source_ref="x", subject="GPIO", body="process A at 25C", knowledge=[doc]
    )
    draft = Draft(
        answer_mode="technical_answer",
        subject="r",
        body="10uA",
        knowledge_refs=[doc["ref"]],
        missing_information=[],
        limitations=[],
    )
    with pytest.raises(ValueError, match="applicability"):
        validate_draft(draft, request)
    from mail_jira_assistant.contracts import KnowledgeEvidence

    draft.evidence = [
        KnowledgeEvidence(
            ref=doc["ref"],
            excerpt="Only process A at 25C.",
            applicable=True,
            conditions=["process A", "25C"],
        )
    ]
    validate_draft(draft, request)
    draft.evidence[0].applicable = False
    with pytest.raises(ValueError):
        validate_draft(draft, request)
    request.limitations = ["측정 온도 불명"]
    with pytest.raises(ValueError, match="coverage"):
        validate_draft(draft, request)
    (tmp_path / "gpio.md").write_text("# GPIO\nNew version")
    assert kb.read("gpio.md")["ref"] != doc["ref"]


def test_changed_knowledge_marks_reviewed_draft_stale(tmp_path):
    inbox = tmp_path / "in"
    runtime = tmp_path / "state"
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "gpio.md").write_text("# GPIO conditions")
    mail(inbox, "GPIO", "GPIO 질문입니다.", "<1@test>")
    sync(runtime, inbox)
    enqueue(runtime)
    worker(runtime, FakeRunner(), kb)
    client = TestClient(create_app(runtime, kb))
    iid = client.get("/api/inquiries").json()[0]["id"]
    client.put(
        "/api/drafts/" + iid,
        json={"version": 1, "body": "보존할 내용", "review": "reviewed"},
    )
    (kb / "gpio.md").write_text("# GPIO changed")
    assert "재검토 필요" in client.get("/inquiries/" + iid).text
    db = connect(runtime)
    d = db.execute("SELECT * FROM drafts").fetchone()
    assert (
        d["freshness"] == "stale"
        and d["body"] == "보존할 내용"
        and d["review"] == "reviewed"
    )
    db.close()


def test_cid_preview_and_untrusted_attachment_download(tmp_path):
    from email.message import EmailMessage

    inbox = tmp_path / "in"
    inbox.mkdir()
    runtime = tmp_path / "state"
    m = EmailMessage()
    m["Subject"] = "CID"
    m["Message-ID"] = "<cid@test>"
    m.set_content("회로 첨부합니다.")
    m.add_attachment(
        b'<svg onload="bad()"/>',
        maintype="image",
        subtype="svg+xml",
        filename="../../bad.svg",
        cid="<circuit>",
    )
    (inbox / "a.eml").write_bytes(m.as_bytes())
    sync(runtime, inbox)
    client = TestClient(create_app(runtime))
    s = client.get("/api/inquiries").json()[0]
    a = json.loads(s["attachments"])[0]
    response = client.get("/attachments/" + s["id"] + "/" + a["id"] + "?inline=true")
    assert response.headers["content-disposition"].startswith("attachment")
    assert response.headers["content-type"] == "application/octet-stream"
    assert a["cid"] == "<circuit>" and a["status"] == "needs_vision"


def test_quote_and_signature_separation_is_recoverable(tmp_path):
    from mail_jira_assistant.documents import normalize_text

    body, excluded = normalize_text("새 GPIO 질문입니다.\n> 과거 회신\n-- \n반복 서명")
    assert body == "새 GPIO 질문입니다." and "과거 회신" in excluded["quoted_text"]
    assert "반복 서명" in excluded["signature"]
    inbox = tmp_path / "in"
    runtime = tmp_path / "state"
    mail(
        inbox, "quoted", "새 GPIO 질문입니다.\n> 과거 회신\n-- \n반복 서명", "<q@test>"
    )
    sync(runtime, inbox)
    db = connect(runtime)
    r = db.execute("SELECT snapshot FROM revisions").fetchone()[0]
    assert "과거 회신" in json.loads(r)["excluded"]["quoted_text"]
    db.close()


def test_kb_change_during_model_call_is_saved_stale(tmp_path):
    inbox = tmp_path / "in"
    runtime = tmp_path / "state"
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "gpio.md").write_text("# GPIO old")
    mail(inbox, "first", "GPIO question", "<k@test>")
    sync(runtime, inbox)
    enqueue(runtime)

    class Changed(FakeRunner):
        def draft(self, r):
            (kb / "gpio.md").write_text("# GPIO new")
            return super().draft(r)

    worker(runtime, Changed(), kb)
    db = connect(runtime)
    assert db.execute("SELECT freshness FROM drafts").fetchone()[0] == "stale"
    db.close()


def test_text_pdf_extracts_real_page_location():
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {NameObject("/F1"): writer._add_object(font)}
            )
        }
    )
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 10 100 Td (GPIO process A) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    out = io.BytesIO()
    writer.write(out)
    result = extract(out.getvalue(), "text.pdf", "application/pdf")
    assert (
        result["status"] == "ready"
        and "GPIO process A" in result["text"]
        and result["locations"] == ["page:1"]
    )
