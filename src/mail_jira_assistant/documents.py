"""Bounded, offline text extraction. Source bytes are never rendered as HTML."""

import csv
import io
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

MAX_BYTES = 20 * 1024 * 1024
MAX_TEXT = 100000


class TextHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self.skip += 1
        if self.skip:
            return
        attrs = dict(attrs)
        if tag in ("p", "br", "div", "tr", "li"):
            self.parts.append("\n")
        if tag in ("td", "th"):
            self.parts.append(" | ")
        if tag == "img":
            self.parts.append("[이미지: " + attrs.get("src", "")[:300] + "]")
        if tag == "a" and attrs.get("href", "").startswith(("https://", "http://")):
            self.parts.append(" [" + attrs["href"][:1000] + "] ")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def normalize_html(text):
    parser = TextHTML()
    parser.feed(text)
    return "\n".join(
        line.strip() for line in "".join(parser.parts).splitlines() if line.strip()
    )


def _extract(data, name, mime):
    result = dict(status="unsupported", text="", locations=[], warnings=[])
    if len(data) > MAX_BYTES:
        return dict(result, status="partial", warnings=["파일 크기 제한 초과"])
    suffix = Path(name or "").suffix.lower()
    try:
        if mime.startswith("image/"):
            return dict(result, status="needs_vision", warnings=["이미지 해석 미지원"])
        if mime.startswith("text/") or suffix in (".txt", ".md", ".csv"):
            text = data.decode("utf-8-sig")
            if suffix == ".csv":
                text = "\n".join(
                    f"row:{i} " + " | ".join(row)
                    for i, row in enumerate(csv.reader(io.StringIO(text)), 1)
                )
            if mime == "text/html":
                text = normalize_html(text)
            result.update(status="ready", text=text, locations=["line:1"])
        elif suffix == ".pdf" or mime == "application/pdf":
            try:
                from pypdf import PdfReader
            except ImportError:
                return dict(result, warnings=["PDF 선택 의존성 pypdf 미설치"])
            reader = PdfReader(io.BytesIO(data))
            pages = [
                f"page:{i}\n{page.extract_text() or ''}"
                for i, page in enumerate(reader.pages[:100], 1)
            ]
            result.update(
                status="ready" if any(len(p) > 15 for p in pages) else "needs_vision",
                text="\n".join(pages),
                locations=[f"page:{i}" for i in range(1, len(pages) + 1)],
            )
            if len(reader.pages) > 100:
                result.update(status="partial", warnings=["100페이지 제한"])
        elif suffix in (".docx", ".xlsx", ".pptx"):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if sum(x.file_size for x in archive.infolist()) > MAX_BYTES:
                    return dict(
                        result, status="partial", warnings=["압축 해제 크기 제한"]
                    )
                names = sorted(
                    n
                    for n in archive.namelist()
                    if (
                        n == "word/document.xml"
                        or n.startswith("ppt/slides/slide")
                        or n.startswith("xl/worksheets/sheet")
                        or n == "xl/sharedStrings.xml"
                    )
                    and n.endswith(".xml")
                )
                shared = []
                if "xl/sharedStrings.xml" in names:
                    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
                    shared = ["".join(e.itertext()) for e in root]
                chunks = []
                for n in names:
                    if n == "xl/sharedStrings.xml":
                        continue
                    root = ET.fromstring(archive.read(n))
                    lines = []
                    if suffix == ".xlsx":
                        ns = {
                            "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
                        }
                        for cell in root.findall(".//s:c", ns):
                            value = cell.find("s:v", ns)
                            text = (
                                value.text or ""
                                if value is not None
                                else "".join(cell.itertext())
                            )
                            if cell.get("t") == "s" and text.isdigit():
                                text = shared[int(text)]
                            if cell.find("s:f", ns) is not None:
                                text += " [수식: 저장된 결과, 재계산 안 함]"
                            lines.append(cell.get("r", "") + ": " + text)
                    else:
                        lines = [
                            e.text
                            for e in root.iter()
                            if e.tag.rsplit("}", 1)[-1] == "t" and e.text
                        ]
                    chunks.append(n + "\n" + "\n".join(lines))
                result.update(status="ready", text="\n".join(chunks), locations=names)
        if len(result["text"]) > MAX_TEXT:
            result.update(
                status="partial",
                text=result["text"][:MAX_TEXT],
                warnings=["추출 문자 제한"],
            )
    except Exception as exc:
        result.update(status="extract_failed", warnings=[type(exc).__name__])
    return result


def extract(data, name, mime, timeout=15, adapter="standard", authorized_path=None):
    """Office/PDF parsers run out of process with a hard wall-clock limit."""
    if (
        Path(name or "").suffix.lower() not in (".pdf", ".docx", ".xlsx", ".pptx")
        and mime != "application/pdf"
    ):
        return _extract(data, name, mime)
    from .process_worker import bounded

    if len(data) > MAX_BYTES:
        return dict(
            status="partial", text="", locations=[], warnings=["파일 크기 제한 초과"]
        )
    if adapter == "word_active" and Path(name or "").suffix.lower() in (
        ".doc",
        ".docx",
        ".rtf",
    ):
        if not authorized_path:
            return dict(
                status="extract_failed",
                text="",
                locations=[],
                warnings=["권한 프로그램에 전달할 보존 원본 경로가 없습니다."],
            )
        return bounded("access", (str(authorized_path), "word_active"), timeout)
    return bounded("extract", (data, name, mime), timeout)


if __name__ == "__main__":
    import json
    import sys

    # Bound address space/CPU on Unix. Timeout remains available on other OSes.
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (12, 12))
    except (ImportError, ValueError, OSError):
        pass
    print(
        json.dumps(
            _extract(
                sys.stdin.buffer.read(MAX_BYTES + 1), "input" + sys.argv[1], sys.argv[2]
            ),
            ensure_ascii=False,
        )
    )


def normalize_text(text):
    """Separate conventional quotes/signature with recoverable text, never destroy raw."""
    main = []
    quoted = []
    signature = []
    in_signature = False
    for line in text.splitlines():
        if line.rstrip() == "--":
            in_signature = True
        if in_signature:
            signature.append(line)
        elif line.lstrip().startswith(">"):
            quoted.append(line)
        else:
            main.append(line)
    body = "\n".join(main).strip()
    if not body:
        return text, {}
    return body, {
        "quoted_text": "\n".join(quoted),
        "signature": "\n".join(signature),
        "normalizer_version": "2",
    }
