"""A brand kit arrives as Word, PowerPoint and PDF files (FORMATS-1).

`sync` read `*.md` and nothing else, though readers for the other formats were
in the package. Now a folder sync reads Markdown, Word, PowerPoint and PDF by
default, and plain text on request. A converted file's claims quote the
converted text, a sidecar gives it frontmatter, and a file with no text is
reported instead of stored empty.

The fixtures are built here, byte by byte, so the test needs no office suite
and no PDF writer: the same minimal files a real exporter writes.
"""

from __future__ import annotations

import uuid
import zipfile

import pytest

from verilore.api.services.ingestion import IngestionService


def _source_text(path, rel_path):
    from verilore.api.services.ingestion import _source_text as convert

    return convert(path, rel_path)


def sync_formats(formats):
    from verilore.api.services.ingestion import sync_formats as choose

    return choose(formats)


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"


def _docx(path, paragraphs):
    """A Word file: (style or None, text) per paragraph."""
    body = "".join(
        f'<w:p>{f"<w:pPr><w:pStyle w:val={chr(34)}{style}{chr(34)}/></w:pPr>" if style else ""}'
        f'<w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>'
        for style, text in paragraphs
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(
            "word/document.xml", f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>'
        )


def _pptx(path, slides):
    """A PowerPoint file: one list of text runs per slide, the first is its title."""
    with zipfile.ZipFile(path, "w") as z:
        for n, texts in enumerate(slides, start=1):
            runs = "".join(f"<a:p><a:r><a:t>{t}</a:t></a:r></a:p>" for t in texts)
            z.writestr(
                f"ppt/slides/slide{n}.xml",
                f'<p:sld xmlns:p="{P}" xmlns:a="{A}"><p:cSld><p:spTree><p:sp><p:txBody>'
                f"{runs}</p:txBody></p:sp></p:spTree></p:cSld></p:sld>",
            )


def _pdf(path, lines):
    """A one-page PDF whose text is `lines`; with no lines, a page with no text (a scan)."""
    ops = "".join(
        f"BT /F1 12 Tf 72 {720 - 20 * i} Td ({line}) Tj ET\n" for i, line in enumerate(lines)
    )
    stream = ops.encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for n, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    path.write_bytes(bytes(out))


# ------------------------------------------------------------- choosing formats


def test_the_default_formats_are_markdown_and_what_a_brand_kit_arrives_as():
    assert sync_formats(None) == (".md", ".markdown", ".docx", ".pptx", ".pdf")
    assert sync_formats("md,txt") == (".markdown", ".md", ".txt")
    assert sync_formats([".PDF"]) == (".pdf",)
    with pytest.raises(ValueError, match="unsupported format 'xlsx'"):
        sync_formats("md,xlsx")


# ------------------------------------------------------------- converting


def test_a_word_file_becomes_markdown_with_its_headings_and_bullets(tmp_path):
    path = tmp_path / "guide.docx"
    _docx(
        path,
        [
            ("Title", "Kaveri brand guide"),
            ("Heading1", "Voice"),
            (None, "Tagline"),
            (None, "Our voice is warm, plain and direct."),
            ("Heading2", "Never"),
            ("ListBullet", "Never use the word premium."),
            ("ListParagraph", "Never promise same-day delivery."),
        ],
    )
    text = _source_text(path, "brand/guide.docx")
    assert text.startswith("---\n") and "tags:\n- docx\n" in text
    # Each Word paragraph is its own Markdown paragraph, and list items are a list.
    assert (
        "Kaveri brand guide\n\n# Voice\n\nTagline\n\nOur voice is warm, plain and direct.\n\n"
        "## Never\n\n- Never use the word premium.\n- Never promise same-day delivery."
    ) in text


def test_a_pdf_keeps_its_labels_lists_and_wrapped_sentences_apart():
    """A PDF holds lines, not paragraphs. Read as one paragraph a page, a
    heading became the first word of the sentence below it ("Voice Our voice is
    warm") and a bullet glyph the first character of a rule."""
    from verilore.api.services.source_formats import _pdf_blocks

    page = (
        "Voice\n"
        "Our voice is warm, plain and direct. We speak to riders as friends, not\n"
        "customers.\n"
        "Never\n"
        "\uf0b7 Never use the word premium.\n"
        "\u2022 Never promise same-day delivery to\n"
        "remote pin codes.\n"
        "Prices: The Trail 2 costs Rs 24,999.\n"
    )
    assert _pdf_blocks(page) == (
        "Voice\n\n"
        "Our voice is warm, plain and direct. We speak to riders as friends, not\n"
        "customers.\n\n"
        "Never\n\n"
        "- Never use the word premium.\n"
        "- Never promise same-day delivery to remote pin codes.\n\n"
        "Prices: The Trail 2 costs Rs 24,999."
    )


def test_a_sidecar_gives_a_file_the_frontmatter_it_cannot_carry(tmp_path):
    path = tmp_path / "rules.pdf"
    _pdf(path, ["Never use the word premium in any copy."])
    (tmp_path / "rules.pdf.yaml").write_text("status: approved\nvalid_until: 2027-01-01\n")
    text = _source_text(path, "brand/rules.pdf")
    assert "status: approved\n" in text and "valid_until: 2027-01-01\n" in text
    assert "Never use the word premium in any copy." in text


@pytest.mark.parametrize(
    "sidecar,reason",
    [("status: [unclosed\n", "invalid_sidecar"), ("- just\n- a list\n", "invalid_sidecar")],
)
def test_a_sidecar_that_cannot_be_read_refuses_the_file(tmp_path, sidecar, reason):
    from verilore.api.services.memory import ClaimValidationError

    path = tmp_path / "rules.pdf"
    _pdf(path, ["Never use the word premium."])
    (tmp_path / "rules.pdf.yaml").write_text(sidecar)
    with pytest.raises(ClaimValidationError) as raised:
        _source_text(path, "brand/rules.pdf")
    assert raised.value.reason.startswith(reason)


def test_a_scanned_pdf_and_a_broken_file_are_refused_with_the_reason(tmp_path):
    from verilore.api.services.memory import ClaimValidationError

    scan = tmp_path / "scan.pdf"
    _pdf(scan, [])
    with pytest.raises(ClaimValidationError) as raised:
        _source_text(scan, "scan.pdf")
    assert raised.value.reason.startswith("no_text: ")
    broken = tmp_path / "broken.docx"
    broken.write_bytes(b"not a zip file")
    with pytest.raises(ClaimValidationError) as raised:
        _source_text(broken, "broken.docx")
    assert raised.value.reason.startswith("unreadable_source: docx")


# ------------------------------------------------------------- syncing


@pytest.fixture
def corpus():
    import asyncio

    from verilore.api.services.corpora import create_corpus
    from verilore.api.services.db import session_scope

    async def make():
        async with session_scope() as db:
            return await create_corpus(db, f"formats-{uuid.uuid4().hex[:12]}", "formats")

    made = asyncio.run(make())
    return made["id"], made["name"]


def _sync(root, corpus_id, **kwargs):
    import asyncio

    return asyncio.run(IngestionService().sync_repo(str(root), corpus_id, **kwargs))


def _claims(corpus):
    import asyncio

    from verilore.api.models.memory import MemoryRequest
    from verilore.api.services import memory_public

    async def read():
        response = await memory_public.execute("current", MemoryRequest(corpus=corpus[1]))
        return {(c.path, c.claim) for c in response.current_memories}

    return asyncio.run(read())


def test_a_folder_of_word_powerpoint_and_pdf_files_is_memory(tmp_path, corpus, monkeypatch):
    monkeypatch.setenv("VERILORE_INGEST_ROOTS", str(tmp_path))
    monkeypatch.setenv("VERILORE_LEXICAL", "1")
    _docx(
        tmp_path / "guide.docx",
        [("Heading1", "Voice"), (None, "Our voice is warm, plain and direct.")],
    )
    _pptx(tmp_path / "deck.pptx", [["Diwali", "Orders close on 5 November 2026."]])
    _pdf(tmp_path / "rules.pdf", ["Never use the word premium in any copy."])
    (tmp_path / "notes.txt").write_text("Plain text is read only when asked for.\n")
    (tmp_path / "README.md").write_text("# Kit\n\n- Markdown is read as before.\n")
    # What Word leaves beside an open document, and what macOS leaves on a USB
    # drive. Neither is a document; read, each would fail the sync.
    (tmp_path / "~$guide.docx").write_bytes(b"\x00owner file")
    (tmp_path / "._deck.pptx").write_bytes(b"\x00\x05\x16\x07 resource fork")

    result = _sync(tmp_path, corpus[0], delete_removed=False)
    assert result["failed"] == 0, result
    assert _claims(corpus) == {
        ("guide.docx", "Our voice is warm, plain and direct."),
        ("deck.pptx", "Orders close on 5 November 2026."),
        ("rules.pdf", "Never use the word premium in any copy."),
        ("README.md", "Markdown is read as before."),
    }

    # Choosing fewer formats, with deletion on, removes nothing it did not read.
    again = _sync(tmp_path, corpus[0], delete_removed=True, formats="md,txt")
    assert again["deleted"] == 0, again
    assert ("rules.pdf", "Never use the word premium in any copy.") in _claims(corpus)
    assert ("notes.txt", "Plain text is read only when asked for.") in _claims(corpus)


def test_a_scanned_pdf_fails_alone_and_says_why(tmp_path, corpus, monkeypatch):
    monkeypatch.setenv("VERILORE_INGEST_ROOTS", str(tmp_path))
    monkeypatch.setenv("VERILORE_LEXICAL", "1")
    _pdf(tmp_path / "scan.pdf", [])
    (tmp_path / "rules.md").write_text("# Rules\n\n- Never use the word premium.\n")
    result = _sync(tmp_path, corpus[0], delete_removed=False)
    assert result["failed"] == 1 and result["added"] == 1
    assert any(error.startswith("scan.pdf: no_text: ") for error in result["errors"]), result


# ------------------------------------------------------------- one reading everywhere


def test_a_pdf_is_read_by_pypdf_first_so_every_machine_reads_the_same_text(tmp_path, monkeypatch):
    """`pdftotext` is on some machines and not others, and lays text out its own
    way. A sync of the same folder from two laptops must not differ by which one
    had it, or every PDF would gain a version on every switch."""
    from verilore.api.services import source_formats

    path = tmp_path / "rules.pdf"
    _pdf(path, ["Never use the word premium in any copy."])

    def refuse(*_args, **_kwargs):
        raise AssertionError("pdftotext was run although pypdf read the file")

    monkeypatch.setattr(source_formats._shutil, "which", lambda _name: "/usr/bin/pdftotext")
    monkeypatch.setattr(source_formats._subprocess, "run", refuse)
    assert "Never use the word premium in any copy." in _source_text(path, "rules.pdf")


# ------------------------------------------------------------- every surface


def test_the_cli_refuses_a_format_it_cannot_read(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from verilore.cli.main import app

    monkeypatch.setenv("VERILORE_INGEST_ROOTS", str(tmp_path))
    result = CliRunner().invoke(
        app, ["ingest-repo", str(tmp_path), "--corpus", "x", "--formats", "md,xlsx"]
    )
    assert result.exit_code == 2, result.output
    assert "unsupported format 'xlsx'" in result.output


@pytest.mark.asyncio
async def test_the_http_sync_takes_formats_and_refuses_one_it_cannot_read():
    from unittest.mock import AsyncMock, patch

    from httpx import ASGITransport, AsyncClient

    from verilore.api.main import app

    summary = {"success": True, "corpus_id": "c1", "message": "sync: +0 ~0 =0 -0 !0"}
    with (
        patch(
            "verilore.api.services.corpora.get_corpus_by_name",
            new_callable=AsyncMock,
            return_value={"id": "c1", "name": "docs", "description": ""},
        ),
        patch(
            "verilore.api.services.ingestion.IngestionService.sync_repo",
            new_callable=AsyncMock,
            return_value=summary,
        ) as sync_repo,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            refused = await c.post(
                "/api/corpora/docs/sync", json={"path": "/some/dir", "formats": ["xlsx"]}
            )
            assert refused.status_code == 422, refused.text
            assert "unsupported format 'xlsx'" in refused.text
            sync_repo.assert_not_called()

            taken = await c.post(
                "/api/corpora/docs/sync", json={"path": "/some/dir", "formats": ["md", "pdf"]}
            )
            assert taken.status_code == 200, taken.text
            assert sync_repo.call_args.kwargs["formats"] == ["md", "pdf"]


def test_the_mcp_sync_tool_takes_formats():
    import inspect

    from verilore import mcp_server

    tool = getattr(mcp_server.sync, "fn", mcp_server.sync)
    parameters = inspect.signature(tool).parameters
    assert "formats" in parameters and parameters["formats"].default is None
    assert "PDF" in (tool.__doc__ or "")
