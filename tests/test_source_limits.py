"""A file built to exhaust the reader is refused, alone, with the reason (SEC-1).

A synced folder is often filled by someone else: an agency's brand kit, a
shared drive. A 40 KB Word file can unpack to gigabytes, a PDF stream can
inflate a thousandfold, and a part that is not XML stopped the whole sync with
a parser error. Each is now refused with a reason that names the limit, and the
rest of the folder still syncs.
"""

from __future__ import annotations

import zipfile
import zlib

import pytest

from test_sync_formats import _docx, _pdf


def _reason(path, rel):
    from verilore.api.services import memory
    from verilore.api.services.ingestion import _source_text

    with pytest.raises(memory.ClaimValidationError) as refused:
        _source_text(path, rel)
    return refused.value.reason


def test_a_word_file_that_unpacks_past_the_limit_is_refused_as_a_bomb(tmp_path, monkeypatch):
    from verilore.api.services import source_formats

    monkeypatch.setattr(source_formats, "MAX_UNPACKED_BYTES", 1_000_000)
    bomb = tmp_path / "bomb.docx"
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", b" " * 2_000_000)
    assert bomb.stat().st_size < 20_000
    reason = _reason(bomb, "bomb.docx")
    assert reason.startswith("unreadable_source:")
    assert "unpacks to more than 1 MB" in reason and "zip bomb" in reason
    # The limit counts what was unpacked, not what the archive says it holds.
    fine = tmp_path / "fine.docx"
    _docx(fine, [(None, "Our voice is warm.")])
    assert "Our voice is warm." in source_formats.parse_file(fine)[1]


def test_an_archive_of_too_many_parts_is_refused(tmp_path, monkeypatch):
    from verilore.api.services import source_formats

    monkeypatch.setattr(source_formats, "MAX_ZIP_MEMBERS", 5)
    many = tmp_path / "many.pptx"
    with zipfile.ZipFile(many, "w") as z:
        for n in range(6):
            z.writestr(f"ppt/slides/slide{n + 1}.xml", "<x/>")
    assert "more than 5 parts" in _reason(many, "many.pptx")


def test_a_part_that_is_not_xml_is_a_reason_and_not_a_crash(tmp_path):
    broken = tmp_path / "broken.docx"
    with zipfile.ZipFile(broken, "w") as z:
        z.writestr("word/document.xml", "<w:document><w:body>never closed")
    reason = _reason(broken, "broken.docx")
    assert reason.startswith("unreadable_source: docx could not be read (not a readable docx")


def test_a_file_over_the_size_limit_is_refused_before_it_is_read(tmp_path, monkeypatch):
    from verilore.api.services import source_formats

    monkeypatch.setattr(source_formats, "MAX_SOURCE_BYTES", 1_000)
    big = tmp_path / "big.md"
    big.write_text("# Big\n\n" + "- A rule that repeats.\n" * 100)
    reason = _reason(big, "big.md")
    assert reason.startswith("too_large:") and "split it" in reason
    pdf = tmp_path / "big.pdf"
    _pdf(pdf, ["Line"] * 80)
    assert _reason(pdf, "big.pdf").startswith("too_large:")


def test_a_pdf_with_more_pages_than_any_kit_needs_is_refused(tmp_path, monkeypatch):
    from verilore.api.services import source_formats

    monkeypatch.setattr(source_formats, "MAX_PDF_PAGES", 0)
    pdf = tmp_path / "rules.pdf"
    _pdf(pdf, ["Never use the word premium in any copy."])
    assert "it has 1 pages; the limit is 0" in _reason(pdf, "rules.pdf")


def test_the_last_resort_pdf_reader_bounds_what_it_inflates(tmp_path, monkeypatch):
    """When pypdf and pdftotext cannot read a file, a small reader of our own
    tries; it inflated every stream without a limit."""
    from verilore.api.services import source_formats

    monkeypatch.setattr(source_formats, "MAX_UNPACKED_BYTES", 1_000_000)
    monkeypatch.setattr(source_formats._shutil, "which", lambda _name: None)
    bomb = tmp_path / "bomb.pdf"
    bomb.write_bytes(
        b"%PDF-1.4\nnot a real object\nstream\n"
        + zlib.compress(b" " * 2_000_000)
        + b"\nendstream\n"
    )
    assert "zip bomb" in _reason(bomb, "bomb.pdf")


def test_a_bad_file_fails_alone_and_the_folder_still_syncs(tmp_path, monkeypatch):
    import asyncio
    import uuid

    from verilore.api.models.memory import MemoryRequest
    from verilore.api.services import memory_public, source_formats
    from verilore.api.services.corpora import create_corpus
    from verilore.api.services.db import session_scope
    from verilore.api.services.ingestion import IngestionService

    monkeypatch.setenv("VERILORE_INGEST_ROOTS", str(tmp_path))
    monkeypatch.setenv("VERILORE_LEXICAL", "1")
    monkeypatch.setattr(source_formats, "MAX_UNPACKED_BYTES", 1_000_000)
    with zipfile.ZipFile(tmp_path / "bomb.docx", "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", b" " * 2_000_000)
    (tmp_path / "rules.md").write_text("# Rules\n\n- Never use the word premium.\n")

    async def make():
        async with session_scope() as db:
            return await create_corpus(db, f"limits-{uuid.uuid4().hex[:10]}", "limits")

    corpus = asyncio.run(make())
    result = asyncio.run(
        IngestionService().sync_repo(str(tmp_path), corpus["id"], delete_removed=False)
    )
    assert result["failed"] == 1, result
    assert any("bomb.docx" in str(error) and "zip bomb" in str(error) for error in result["errors"])
    current = asyncio.run(memory_public.execute("current", MemoryRequest(corpus=corpus["name"])))
    assert [c.claim for c in current.current_memories] == ["Never use the word premium."]


def test_the_install_jobs_retry_a_download_instead_of_failing_on_a_dns_blip():
    from pathlib import Path

    script = (Path(__file__).resolve().parents[1] / "scripts/ci/install_and_run.sh").read_text()
    assert "--retry-all-errors" in script
    assert "install.sh | env" not in script
