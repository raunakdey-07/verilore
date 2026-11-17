# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Raunak Dey

"""Source format parsers.

Every parser produces the same canonical representation:

    (metadata: dict, body: str)

so format-specific semantics never leak into retrieval. Markdown is the
canonical format; other formats are converted to it.
"""

from __future__ import annotations

import re
from pathlib import Path

from verilore.api.services.parser import parse_markdown

#: What one file may cost to read. A brand kit's largest file is a few MB; a
#: folder someone else filled can hold a file built to exhaust the reader: a
#: 40 KB Word file can unpack to gigabytes. Each limit refuses that one file,
#: with the reason, and the rest of the folder still syncs.
MAX_SOURCE_BYTES = 50_000_000
MAX_UNPACKED_BYTES = 200_000_000
MAX_ZIP_MEMBERS = 10_000
MAX_PDF_PAGES = 3_000


def parse_file(path: str | Path) -> tuple[dict, str]:
    """Parse a file into (metadata, body) based on its extension.

    Supported: .md/.markdown (canonical), .txt, source code, .json, .yaml/.yml,
    .docx, .pptx and .pdf. Raises ValueError for an unsupported extension, a
    file over the size limits above, or a file that is not what its extension
    says.
    """
    p = Path(path)
    suffix = p.suffix.lower()
    size = p.stat().st_size
    if size > MAX_SOURCE_BYTES:
        raise ValueError(
            f"the file is {size / 1_000_000:.0f} MB; the limit for one file is "
            f"{MAX_SOURCE_BYTES // 1_000_000} MB"
        )
    if suffix in (".docx", ".pptx", ".pdf"):
        try:
            return {".docx": _parse_docx, ".pptx": _parse_pptx, ".pdf": _parse_pdf}[suffix](p)
        except (
            _ET.ParseError,
            _zipfile.BadZipFile,
            RuntimeError,
            NotImplementedError,
            EOFError,
        ) as exc:
            # A malformed part, an encrypted archive, an unknown compression: the
            # file is not what its name says, and that is the reader's to fix.
            raise ValueError(f"not a readable {suffix.lstrip('.')} file ({exc})") from None

    if suffix in (".md", ".markdown"):
        content = p.read_text(encoding="utf-8")
        return parse_markdown(content)
    if suffix == ".txt":
        content = p.read_text(encoding="utf-8")
        return _parse_plain_text(p, content)
    if suffix in _CODE_EXTENSIONS:
        content = p.read_text(encoding="utf-8")
        return _parse_code(p, content)
    if suffix == ".json":
        content = p.read_text(encoding="utf-8")
        return _parse_json(p, content)
    if suffix in (".yaml", ".yml"):
        content = p.read_text(encoding="utf-8")
        return _parse_yaml(p, content)
    raise ValueError(f"unsupported source format: {suffix}")


def _synthesized_metadata(
    title: str,
    doc_type: str,
    tags: list[str],
    summary: str,
) -> dict:
    """Build frontmatter-equivalent metadata for non-Markdown sources."""
    return {
        "title": title,
        "date": None,
        "tags": tags,
        "document_type": doc_type if doc_type in ("kaggle", "project", "note", "paper") else "note",
        "summary": summary,
    }


def _parse_plain_text(p: Path, content: str) -> tuple[dict, str]:
    first_line = next((ln.strip() for ln in content.splitlines() if ln.strip()), p.stem)
    title = first_line[:120]
    meta = _synthesized_metadata(title, "note", ["text"], f"Plain text document: {p.name}")
    # Promote the first line to a Markdown heading so chunking keeps context.
    body = f"# {title}\n\n{content.strip()}"
    return meta, body


def _parse_code(p: Path, content: str) -> tuple[dict, str]:
    lang = _CODE_EXTENSIONS[p.suffix.lower()]
    title = f"{p.name} ({lang})"
    meta = _synthesized_metadata(title, "note", ["code", lang], f"Source code file {p.name}")
    fenced = f"# {p.name}\n\n```{lang}\n{content.strip()}\n```\n"
    return meta, fenced


def _parse_json(p: Path, content: str) -> tuple[dict, str]:
    import json as _json

    try:
        data = _json.loads(content)
        keys = ", ".join(list(data.keys())[:10]) if isinstance(data, dict) else ""
        summary = f"JSON document with keys: {keys}" if keys else "JSON document"
    except _json.JSONDecodeError:
        summary = "JSON document (unparseable)"
    title = p.stem
    meta = _synthesized_metadata(title, "note", ["json"], summary)
    fenced = f"# {p.stem}\n\n```json\n{content.strip()}\n```\n"
    return meta, fenced


def _parse_yaml(p: Path, content: str) -> tuple[dict, str]:
    import yaml as _yaml

    try:
        data = _yaml.safe_load(content)
        keys = ", ".join(list(data.keys())[:10]) if isinstance(data, dict) else ""
        summary = f"YAML document with keys: {keys}" if keys else "YAML document"
    except _yaml.YAMLError:
        summary = "YAML document (unparseable)"
    title = p.stem
    meta = _synthesized_metadata(title, "note", ["yaml"], summary)
    fenced = f"# {p.stem}\n\n```yaml\n{content.strip()}\n```\n"
    return meta, fenced


_CODE_EXTENSIONS = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".sh": "bash",
    ".sql": "sql",
}

SUPPORTED_EXTENSIONS = {
    ".md",
    ".markdown",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
    ".docx",
    ".pptx",
    ".pdf",
} | set(_CODE_EXTENSIONS.keys())


def _end_block(lines: list) -> None:
    """End the Markdown block in progress, so the next line starts a new one."""
    if lines and lines[-1] != "":
        lines.append("")


class _Unpacked:
    """How much of a Word or PowerPoint file has been unpacked so far."""

    def __init__(self) -> None:
        self.used = 0

    def read(self, z, name: str) -> bytes:
        """One part of the archive, refused past `MAX_UNPACKED_BYTES` in all.

        Read through a bounded stream, not `ZipFile.read`, because the size an
        archive declares is the archive's own claim: a bomb declares a small one.
        """
        left = MAX_UNPACKED_BYTES - self.used
        with z.open(name) as part:
            data = part.read(left + 1)
        if len(data) > left:
            raise ValueError(
                f"it unpacks to more than {MAX_UNPACKED_BYTES // 1_000_000} MB, "
                "which no document needs; refused as a possible zip bomb"
            )
        self.used += len(data)
        return data


def _open_zip(p, kind: str):
    try:
        z = _zipfile.ZipFile(str(p))
    except _zipfile.BadZipFile:
        raise ValueError("invalid %s" % kind)
    if len(z.infolist()) > MAX_ZIP_MEMBERS:
        raise ValueError(f"it holds more than {MAX_ZIP_MEMBERS} parts, which no {kind} needs")
    return z, _Unpacked()


def _parse_docx(p):
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    W = "{%s}" % ns
    z, unpacked = _open_zip(p, "docx")
    try:
        doc_xml = unpacked.read(z, "word/document.xml")
    except KeyError:
        raise ValueError("unsupported source format: .docx")
    root = _ET.fromstring(doc_xml)
    body = root.find(W + "body")
    lines = []
    if body is not None:
        for child in body:
            tag = child.tag.split("}")[-1]
            if tag == "p":
                ppr = child.find(W + "pPr")
                pstyle = None
                listed = False
                if ppr is not None:
                    ps = ppr.find(W + "pStyle")
                    if ps is not None:
                        pstyle = ps.get(W + "val")
                    # A bulleted or numbered paragraph carries numbering
                    # properties, or a list style ("List Bullet", "ListParagraph").
                    listed = ppr.find(W + "numPr") is not None
                listed = listed or bool(pstyle and pstyle.lower().startswith("list"))
                texts = [t.text or "" for t in child.iter(W + "t")]
                text = "".join(texts)
                if not text.strip():
                    lines.append("")
                    continue
                if pstyle and pstyle.lower().startswith("heading"):
                    m = _re2.search(r"(\d+)", pstyle)
                    level = min(int(m.group(1)), 6) if m else 1
                    _end_block(lines)
                    lines.append("#" * level + " " + text.strip())
                    lines.append("")
                elif listed:
                    # Items of one list stay together, as a Markdown list.
                    lines.append("- " + text.strip())
                else:
                    # Each Word paragraph is its own Markdown paragraph: run
                    # together, "Tagline" and the sentence after it read as
                    # one sentence.
                    _end_block(lines)
                    lines.append(text.strip())
                    lines.append("")
            elif tag == "tbl":
                _end_block(lines)
                rows = []
                for tr in child.findall(W + "tr"):
                    cells = []
                    for tc in tr.findall(W + "tc"):
                        ctext = "".join(t.text or "" for t in tc.iter(W + "t"))
                        cells.append(ctext.strip().replace("|", "\\|"))
                    rows.append(cells)
                if not rows:
                    continue
                header = rows[0]
                lines.append("| " + " | ".join(header) + " |")
                lines.append("| " + " | ".join(["---"] * len(header)) + " |")
                for r in rows[1:]:
                    while len(r) < len(header):
                        r.append("")
                    lines.append("| " + " | ".join(r[: len(header)]) + " |")
                lines.append("")
    body_text = "\n".join(lines).strip()
    title = p.stem
    try:
        cp = unpacked.read(z, "docProps/core.xml")
        croot = _ET.fromstring(cp)
        for el in croot.iter():
            if el.tag.endswith("}title") and el.text:
                title = el.text.strip()
    except KeyError:
        pass
    meta = _synthesized_metadata(title, "note", ["docx"], "DOCX document: %s" % p.name)
    body = "# %s\n\n%s" % (title, body_text) if body_text else "# %s\n" % title
    return meta, body


def _parse_pptx(p):
    A = "http://schemas.openxmlformats.org/drawingml/2006/main"
    AT = "{%s}" % A
    z, unpacked = _open_zip(p, "pptx")
    slide_files = sorted(
        [n for n in z.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")],
        key=lambda x: (
            int(_re2.search(r"slide(\d+)", x).group(1)) if _re2.search(r"slide(\d+)", x) else 0
        ),
    )
    lines = []
    title = p.stem
    for idx, sf in enumerate(slide_files, start=1):
        try:
            root = _ET.fromstring(unpacked.read(z, sf))
        except _ET.ParseError:
            continue
        texts = [t.text for t in root.iter(AT + "t") if t.text]
        notes_text = ""
        rels_path = sf.replace("slides/slide", "slides/_rels/slide").replace(".xml", ".xml.rels")
        notes_file = None
        try:
            rels = _ET.fromstring(unpacked.read(z, rels_path))
            for rel in rels:
                if "notesSlide" in (rel.get("Type") or ""):
                    target = rel.get("Target", "")
                    notes_file = "ppt/" + target.lstrip("../").lstrip("/")
        except KeyError:
            pass
        if notes_file:
            try:
                nroot = _ET.fromstring(unpacked.read(z, notes_file))
                ntexts = [t.text for t in nroot.iter(AT + "t") if t.text]
                notes_text = " ".join(ntexts).strip()
            except KeyError:
                pass
        slide_title = texts[0].strip() if texts else None
        heading = slide_title if slide_title else "Slide %d" % idx
        lines.append("## Slide %d: %s" % (idx, heading))
        lines.append("")
        for t in texts[1:]:
            t = t.strip()
            if t:
                lines.append("- " + t)
        if notes_text:
            lines.append("")
            lines.append("> Speaker notes: " + notes_text)
        lines.append("")
    body_text = "\n".join(lines).strip()
    try:
        cp = unpacked.read(z, "docProps/core.xml")
        croot = _ET.fromstring(cp)
        for el in croot.iter():
            if el.tag.endswith("}title") and el.text:
                title = el.text.strip()
    except KeyError:
        pass
    meta = _synthesized_metadata(title, "note", ["pptx"], "PPTX presentation: %s" % p.name)
    body = "# %s\n\n%s" % (title, body_text) if body_text else "# %s\n" % title
    return meta, body


def _pypdf_text(p) -> str:
    """The PDF's text layer, page by page with form feeds between, read by pypdf.

    Tried first because it is a declared dependency: the same file reads to the
    same text on every machine, so a folder synced from two laptops does not
    record a new version of every PDF. Empty when pypdf cannot read the file.
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        reader = PdfReader(str(p))
        pages = len(reader.pages)
    except Exception:  # noqa: BLE001 - a broken file falls through to the next reader
        return ""
    if pages > MAX_PDF_PAGES:
        raise ValueError(f"it has {pages} pages; the limit is {MAX_PDF_PAGES}")
    try:
        return "\f".join((page.extract_text() or "") for page in reader.pages)
    except Exception:  # noqa: BLE001
        return ""


def _parse_pdf(p):
    text = _pypdf_text(p)
    try:
        if not text.strip() and _shutil.which("pdftotext"):
            out = _subprocess.run(
                ["pdftotext", "-layout", str(p), "-"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if out.returncode == 0:
                text = out.stdout
    except Exception:
        text = ""
    if not text.strip():
        text = _pdf_stdlib_extract(p)
    title = p.stem
    meta = _synthesized_metadata(title, "note", ["pdf"], "PDF document: %s" % p.name)
    pages = text.split("\f")
    lines = []
    for i, pg in enumerate(pages, start=1):
        pg = _pdf_blocks(pg)
        if not pg:
            continue
        lines.append("## Page %d" % i)
        lines.append("")
        lines.append(pg)
        lines.append("")
    body_text = "\n".join(lines).strip()
    body = "# %s\n\n%s" % (title, body_text) if body_text else "# %s\n" % title
    return meta, body


#: A line a PDF draws as a list item: a bullet glyph and a space. `\uf0b7` and
#: `\uf0a7` are the Symbol and Wingdings bullets Word writes into its PDFs.
_PDF_BULLET = re.compile(r"^[\u2022\u2023\u2043\u25aa\u25cf\u25e6\u25a0\uf0b7\uf0a7\u2013*-]\s+")
#: How a sentence, a list item or a label ends.
_PDF_END = (".", "!", "?", ":", ";", ")", '"', "\u201d")


def _pdf_blocks(page: str) -> str:
    """A page of PDF text as Markdown blocks.

    A PDF keeps lines, not paragraphs, so the structure is recovered from the
    lines: a bullet glyph starts a list item; a short line that ends in no
    punctuation is a label or a heading ("Voice", "Never") and stands alone,
    instead of becoming the first words of the sentence below it; a line that
    continues a sentence stays with it.
    """
    blocks: list[str] = []
    current: list[str] = []
    item = False

    def flush():
        nonlocal current, item
        if current:
            blocks.append("\n".join(current))
        current, item = [], False

    for raw in page.splitlines():
        line = " ".join(raw.split())
        if not line:
            flush()
            continue
        bullet = _PDF_BULLET.match(line)
        if bullet:
            if not item:
                flush()
            item = True
            current.append("- " + line[bullet.end() :])
            continue
        label = len(line.split()) <= 6 and not line.endswith(_PDF_END)
        continues = bool(current) and not current[-1].endswith(_PDF_END) and line[:1].islower()
        if continues:
            current[-1] = current[-1] + " " + line if item else current[-1]
            if not item:
                current.append(line)
            continue
        if label:
            flush()
            blocks.append(line)
            continue
        if item:
            flush()
        current.append(line)
    flush()
    return "\n\n".join(blocks)


def _pdf_stdlib_extract(p):
    try:
        data = p.read_bytes()
    except Exception:
        return ""
    out = []
    left = MAX_UNPACKED_BYTES
    for m in _re2.finditer(rb"stream\r?\n(.*?)endstream", data, _re2.DOTALL):
        raw = m.group(1)
        try:
            # Bounded: a stream can inflate a thousandfold, and this reader is
            # the one that runs when the others could not read the file.
            d = _zlib.decompressobj().decompress(raw.strip(), left + 1)
        except Exception:
            d = raw
        if len(d) > left:
            raise ValueError(
                f"it unpacks to more than {MAX_UNPACKED_BYTES // 1_000_000} MB, "
                "which no document needs; refused as a possible zip bomb"
            )
        left -= len(d)
        for tm in _re2.finditer(rb"\((?:\\.|[^()])*\)\s*Tj", d):
            s = tm.group(0)
            start = s.find(b"(")
            end = s.rfind(b")")
            if start != -1 and end != -1:
                chunk = s[start + 1 : end]
                chunk = chunk.replace(b"\\(", b"(").replace(b"\\)", b")").replace(b"\\\\", b"\\")
                try:
                    out.append(chunk.decode("latin-1"))
                except Exception:
                    pass
        for tm in _re2.finditer(rb"\[(.*?)\]\s*TJ", d, _re2.DOTALL):
            arr = tm.group(1)
            for sm in _re2.finditer(rb"\((?:\\.|[^()])*\)", arr):
                s = sm.group(0)
                chunk = s[1:-1]
                chunk = chunk.replace(b"\\(", b"(").replace(b"\\)", b")").replace(b"\\\\", b"\\")
                try:
                    out.append(chunk.decode("latin-1"))
                except Exception:
                    pass
    return " ".join(out)


import zipfile as _zipfile  # noqa: E402
import xml.etree.ElementTree as _ET  # noqa: E402
import zlib as _zlib  # noqa: E402
import re as _re2  # noqa: E402
import subprocess as _subprocess  # noqa: E402
import shutil as _shutil  # noqa: E402
