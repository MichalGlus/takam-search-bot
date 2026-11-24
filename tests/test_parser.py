import io

import docx
import pytest

from takam_search.chunker import chunk_document
from takam_search.parser import ParseError, parse_docx


def _docx_bytes(build) -> bytes:
    d = docx.Document()
    build(d)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------- real documents

def test_section_numbers_are_computed_from_word_numbering(docx_path):
    parsed = parse_docx(docx_path("H.1.3.1"))
    by_text = {b.text[:40]: b for b in parsed.blocks}
    digital = next(b for b in parsed.blocks if "חתימה דיגיטלית" in b.text and b.kind == "para" and "סיגמה" in b.text)
    assert digital.number == "2.1.5"
    assert digital.heading_path[-1] == "2.1 חתימה על התחייבויות"
    # level-4 style takes numId from its base style and ilvl from itself
    assert any(b.number == "2.1.2.1" for b in parsed.blocks)
    assert by_text  # sanity


def test_numbering_switched_off_paragraph_has_no_number(docx_path):
    parsed = parse_docx(docx_path("H.1.3.1"))
    block = next(b for b in parsed.blocks if b.text.startswith("להנחות את משרדי הממשלה"))
    assert block.number is None  # numId=0 in the paragraph overrides the style


def test_tables_are_kept_in_order_with_header_labels(docx_path):
    parsed = parse_docx(docx_path("H.1.3.1"))
    rows = [b for b in parsed.blocks if b.kind == "table"]
    assert any(b.text == "רמת אישור: 3 | סכום ב- ₪: 43,000" for b in rows)
    assert rows[0].heading_path == ("נספח ד - רמות הרשאה על פי חוק נכסי המדינה",)


def test_change_log_table_is_metadata_not_content(docx_path):
    parsed = parse_docx(docx_path("H.1.3.1"))
    assert len(parsed.change_log) == 4
    assert parsed.change_log[0]["מהדורה"] == "2"
    assert not any("טבלת שינויים" in b.text and b.kind == "table" for b in parsed.blocks)


def test_unstyled_document_still_yields_chunks(docx_path):
    # H.1.1.1 (glossary, 26K chars) has no structural styles at all.
    chunks = chunk_document(parse_docx(docx_path("H.1.1.1")))
    assert len(chunks) > 10
    assert all(len(c.body) <= 1100 for c in chunks)


def test_tiny_redirect_document_is_not_dropped(docx_path):
    # H.1.3.3 only points to the temporary instruction HZ.1.3.3.1.
    chunks = chunk_document(parse_docx(docx_path("H.1.3.3")))
    assert len(chunks) == 1 and "כתבי שיפוי" in chunks[0].text


def test_hyperlink_field_codes_do_not_leak_into_text(docx_path):
    text = parse_docx(docx_path("H.1.3.1")).text
    assert "HYPERLINK" not in text and "\\l" not in text


# ---------------------------------------------------------------- synthetic edge cases

def test_empty_file_raises_parse_error():
    with pytest.raises(ParseError):
        parse_docx(b"")


def test_corrupt_file_raises_parse_error():
    with pytest.raises(ParseError):
        parse_docx(b"PK\x03\x04 this is not really a zip")


def test_document_without_text_yields_no_blocks():
    parsed = parse_docx(_docx_bytes(lambda d: None))
    assert parsed.blocks == [] and chunk_document(parsed) == []


def test_heading_with_no_content_is_kept_as_text():
    def build(d):
        d.add_heading("כותרת ראשית", level=1)
        d.add_paragraph("שורה קצרה בלי נקודה")
        d.add_heading("כותרת שנייה", level=1)

    parsed = parse_docx(_docx_bytes(build))
    texts = [b.text for b in parsed.blocks]
    assert "כותרת שנייה" in texts  # an empty heading is not lost


def test_generic_table_rows_use_header_labels():
    def build(d):
        d.add_heading("נתונים", level=1)
        t = d.add_table(rows=3, cols=2)
        for i, row in enumerate([("שם", "סכום"), ("א", "10"), ("ב", "20")]):
            for j, v in enumerate(row):
                t.cell(i, j).text = v

    parsed = parse_docx(_docx_bytes(build))
    assert [b.text for b in parsed.blocks if b.kind == "table"] == ["שם: א | סכום: 10", "שם: ב | סכום: 20"]


def test_long_paragraph_is_split_with_overlap():
    sentence = "חשב המשרד יוודא כי כל הפעולות מתבצעות כנדרש בהתאם להוראות. "
    parsed = parse_docx(_docx_bytes(lambda d: d.add_paragraph(sentence * 60)))
    chunks = chunk_document(parsed, max_chars=500)
    assert len(chunks) > 1
    assert all(len(c.body) <= 600 for c in chunks)
    # consecutive windows share a sentence
    assert chunks[0].body.split(". ")[-1][:20] in chunks[1].body


def test_chunk_keeps_heading_path_and_section_range(docx_path):
    chunks = chunk_document(parse_docx(docx_path("H.1.3.1")))
    c = next(c for c in chunks if "2.1.5" in c.body)
    assert c.heading_path.startswith("2 הנחיות לביצוע")
    assert c.text.startswith(c.heading_path)
    assert c.section is not None
