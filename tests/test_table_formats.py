"""A pricing table in Word, PowerPoint and PDF: what a sync reads from it (DOCS-1, #36).

An agency's kit puts prices in a table: plan in one column, price in the next.
A claim is only checkable when the row stays together ("Plus ... £5"), because
`check` compares a price with the line that names its plan. Word, PowerPoint
and PDF tables were untested. These fixtures are built here, byte by byte, as
the formats' own exporters write them, and pin what a sync reads now:

* **Word**: a row is read as one line, and is a claim.
* **PowerPoint**: each cell is its own run, so a row is split, and no claim
  holds a plan with its price.
* **PDF**: the row's cells sit on one line of the text layer, and the lines
  ("Plus GBP 5 a month") are not sentences: the table gives no claims at all.

The PowerPoint and PDF tests pin today's gap: they pass now and fail the day
#36 is fixed (0.12.3), and then they change to assert that the rows are kept.
They are not expected failures, because the skip gate counts an xfail as a
skip, and CI allows no skip it has not been told about.
"""

from __future__ import annotations

import uuid
import zipfile

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
ROWS = [("Plan", "Price"), ("Extra", "£3 a month"), ("Plus", "£5 a month"), ("Perks", "£9 a month")]


def _docx(path):
    cell = '<w:tc><w:p><w:r><w:t xml:space="preserve">{}</w:t></w:r></w:p></w:tc>'
    rows = "".join("<w:tr>" + "".join(cell.format(c) for c in row) + "</w:tr>" for row in ROWS)
    body = f"<w:p><w:r><w:t>Plans</w:t></w:r></w:p><w:tbl>{rows}</w:tbl>"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(
            "word/document.xml", f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>'
        )


def _pptx(path):
    cell = "<a:tc><a:txBody><a:p><a:r><a:t>{}</a:t></a:r></a:p></a:txBody></a:tc>"
    rows = "".join("<a:tr>" + "".join(cell.format(c) for c in row) + "</a:tr>" for row in ROWS)
    title = "<p:sp><p:txBody><a:p><a:r><a:t>Plans</a:t></a:r></a:p></p:txBody></p:sp>"
    table = (
        "<p:graphicFrame><a:graphic><a:graphicData>"
        f"<a:tbl>{rows}</a:tbl>"
        "</a:graphicData></a:graphic></p:graphicFrame>"
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(
            "ppt/slides/slide1.xml",
            f'<p:sld xmlns:p="{P}" xmlns:a="{A}"><p:cSld><p:spTree>{title}{table}'
            "</p:spTree></p:cSld></p:sld>",
        )


def _pdf(path):
    """One page: a title, then each row's two cells drawn at two columns of one line."""
    ops = "BT /F1 14 Tf 72 740 Td (Plans) Tj ET\n"
    for i, (plan, price) in enumerate(ROWS):
        y = 700 - 20 * i
        price = price.replace("£", "GBP ")
        ops += f"BT /F1 12 Tf 72 {y} Td ({plan}) Tj ET\nBT /F1 12 Tf 220 {y} Td ({price}) Tj ET\n"
    stream = ops.encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>"
        ),
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


def _claims(tmp_path, monkeypatch, name, build):
    from verilore import Verilore

    monkeypatch.setenv("VERILORE_INGEST_ROOTS", str(tmp_path))
    monkeypatch.setenv("VERILORE_LEXICAL", "1")
    folder = tmp_path / "kit"
    folder.mkdir()
    build(folder / name)
    client = Verilore(f"tables-{uuid.uuid4().hex[:10]}")
    summary = client.sync(str(folder))
    assert summary.failed == 0, summary
    return [c.claim for c in client.memory.current().current_memories]


def _rows_kept(claims, currency):
    return all(
        any(plan in claim and price.replace("£", currency) in claim for claim in claims)
        for plan, price in ROWS[1:]
    )


def test_a_word_table_row_is_one_claim(tmp_path, monkeypatch):
    claims = _claims(tmp_path, monkeypatch, "plans.docx", _docx)
    assert _rows_kept(claims, "£"), claims


def test_a_powerpoint_table_row_is_split_today(tmp_path, monkeypatch):
    """#36: a PowerPoint table's cells are read one by one, so no claim keeps a row."""
    claims = _claims(tmp_path, monkeypatch, "plans.pptx", _pptx)
    assert not _rows_kept(claims, "£"), "#36 is fixed: assert the rows are kept"


def test_a_pdf_table_gives_no_claims_today(tmp_path, monkeypatch):
    """#36: a PDF table's lines are not sentences, so the table gives no claims."""
    claims = _claims(tmp_path, monkeypatch, "plans.pdf", _pdf)
    assert claims == [], f"#36 is fixed: assert the rows are kept ({claims})"
