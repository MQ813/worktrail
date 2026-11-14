"""Authorized program access, not DRM removal. Run only in a logged-in session."""

from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path

from .documents import normalize_html


def normalized(message, adapter):
    body = message.get_body(preferencelist=("plain", "html"))
    text = body.get_content() if body else ""
    if body and body.get_content_type() == "text/html":
        text = normalize_html(text)
    images = any(p.get_content_type().startswith("image/") for p in message.walk())
    return dict(
        status="partial"
        if text.strip() and images
        else ("ready" if text.strip() else "extract_failed"),
        text=text,
        locations=["body"],
        warnings=(["이미지 해석 미지원"] if images else [])
        + ([] if text.strip() else ["본문 접근 실패 또는 빈 본문: 확인 필요"]),
        subject=str(message.get("Subject", "")),
        sender=str(message.get("From", "")),
        recipients=str(message.get("To", "")),
        date=str(message.get("Date", "")),
        adapter=adapter,
    )


def read_in_worker(path, adapter):
    if adapter == "eml":
        msg = BytesParser(policy=policy.default).parsebytes(Path(path).read_bytes())
        if msg.defects or not msg.keys():
            raise ValueError("invalid_mime")
        return normalized(msg, adapter)
    if adapter == "fake":
        msg = EmailMessage()
        msg["Subject"] = "합성 권한 문서"
        msg.set_content(Path(path).read_text(encoding="utf-8"))
        return normalized(msg, adapter)
    if adapter == "fake_timeout":
        import time

        time.sleep(60)
    if adapter == "word_active":
        return read_word(path)
    if adapter != "outlook_msg":
        raise ValueError("허용된 adapter가 아닙니다.")
    import pythoncom

    pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
    item = outlook = None
    try:
        import win32com.client

        outlook = win32com.client.Dispatch("Outlook.Application")
        item = outlook.Session.OpenSharedItem(str(Path(path).resolve()))
        msg = EmailMessage()
        for header, prop in [
            ("Subject", "Subject"),
            ("From", "SenderEmailAddress"),
            ("To", "To"),
        ]:
            msg[header] = str(getattr(item, prop, ""))
        msg["Date"] = item.SentOn.strftime("%a, %d %b %Y %H:%M:%S %z")
        msg.set_content(str(item.Body or ""))
        result = normalized(msg, adapter)
        # Attachments may contain DRM or images; never claim complete extraction.
        if item.Attachments.Count:
            result["status"] = "partial"
            result["warnings"].append("COM 첨부는 원본 프로그램에서 확인 필요")
        return result
    finally:
        item = outlook = None  # Do not Quit a user-owned application.
        pythoncom.CoUninitialize()


def read(path, adapter="eml", timeout=20):
    from .process_worker import COM_SERIAL, bounded

    with COM_SERIAL:
        return bounded("access", (str(path), adapter), timeout)


def read_word(path):
    """Use an already authorized Word session; close only our own readonly document."""
    import pythoncom

    pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
    word = document = None
    opened = False
    try:
        import win32com.client

        word = win32com.client.GetActiveObject("Word.Application")
        target = str(Path(path).resolve())
        for existing in word.Documents:
            if str(Path(existing.FullName).resolve()).casefold() == target.casefold():
                raise ValueError(
                    "사용자가 열어 둔 문서는 변경·종료하지 않습니다. 별도 수집 원본으로 확인하세요."
                )
        document = word.Documents.Open(
            target,
            ConfirmConversions=False,
            ReadOnly=True,
            AddToRecentFiles=False,
            Visible=False,
            NoEncodingDialog=True,
        )
        opened = True
        text = str(document.Content.Text or "")
        images = document.InlineShapes.Count + document.Shapes.Count
        return dict(
            status="partial"
            if (images or len(text) > 100000) and text.strip()
            else ("ready" if text.strip() else "extract_failed"),
            text=text[:100000],
            locations=["Word.Content"],
            warnings=(["이미지 해석 미지원"] if images else [])
            + (["본문 접근 실패 또는 빈 본문: 확인 필요"] if not text.strip() else [])
            + (["문서 텍스트 10만자 제한"] if len(text) > 100000 else []),
            adapter="word_active",
        )
    finally:
        try:
            if opened and document is not None:
                document.Close(SaveChanges=0)
        finally:
            document = word = None
            pythoncom.CoUninitialize()
