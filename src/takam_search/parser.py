"""DOCX -> ordered blocks (paragraphs and table rows) with section numbers and heading path.

What the takam DOCX files look like (checked on all chapter-1 files):
- Section numbers are NOT in the text. They come from Word list numbering attached
  to paragraph styles ("סעיף רמה 2/3/4..."), so they are recomputed here from
  numbering.xml. Styles inherit numbering from their base style ("סעיף רמה 22"
  is numbered like "סעיף רמה 2"), and a paragraph can switch numbering off
  (numId=0). Numbers are best-effort: Word's rendering rules are richer than this.
- Tables matter (e.g. approval levels and amounts) and are not part of
  `Document.paragraphs`, so the body is walked in order.
- Almost every file ends with a "טבלת שינויים" (change log) table. It is kept as
  metadata, not indexed as content.
- Some files have no structural styles at all (e.g. a glossary); they still yield
  plain blocks, and the chunker groups them by size.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path

import docx
from docx.document import Document as DocxDocument
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

HEADING_MAX_CHARS = 70
_TOC_LINE = re.compile(r"\t\s*\d+\s*$")


class ParseError(ValueError):
    """The file is not a readable DOCX."""


@dataclass
class Block:
    text: str
    kind: str  # "para" | "table"
    number: str | None = None
    heading_path: tuple[str, ...] = ()


@dataclass
class ParsedDocument:
    blocks: list[Block] = field(default_factory=list)
    change_log: list[dict[str, str]] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(b.text for b in self.blocks)


# --------------------------------------------------------------------------- numbering

def _hebrew_letter(n: int) -> str:
    letters = "אבגדהוזחטיכלמנסעפצקרשת"
    return letters[(n - 1) % len(letters)] if n > 0 else str(n)


def _roman(n: int) -> str:
    vals = [(1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"),
            (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")]
    out = ""
    for v, s in vals:
        while n >= v:
            out += s
            n -= v
    return out


def _format_number(n: int, fmt: str) -> str:
    if fmt in ("lowerLetter", "upperLetter"):
        s = chr(ord("a") + (n - 1) % 26)
        return s.upper() if fmt == "upperLetter" else s
    if fmt in ("hebrew1", "hebrew2"):
        return _hebrew_letter(n)
    if fmt in ("lowerRoman", "upperRoman"):
        s = _roman(n)
        return s.upper() if fmt == "upperRoman" else s
    return str(n)


@dataclass
class _Level:
    start: int = 1
    fmt: str = "decimal"
    text: str = ""
    pstyle: str | None = None


class _Numbering:
    """Minimal resolver for Word list numbering (numbering.xml + style inheritance)."""

    def __init__(self, document: DocxDocument) -> None:
        self.abstract: dict[str, dict[int, _Level]] = {}
        self.num_to_abstract: dict[str, str] = {}
        self.counters: dict[str, list[int]] = {}
        try:
            root = document.part.numbering_part.element
        except (KeyError, NotImplementedError, AttributeError):
            root = None
        if root is not None:
            for an in root.findall(qn("w:abstractNum")):
                levels = {}
                for lvl in an.findall(qn("w:lvl")):
                    def val(tag: str) -> str | None:
                        el = lvl.find(qn(tag))
                        return el.get(qn("w:val")) if el is not None else None
                    levels[int(lvl.get(qn("w:ilvl")))] = _Level(
                        start=int(val("w:start") or 1),
                        fmt=val("w:numFmt") or "decimal",
                        text=val("w:lvlText") or "",
                        pstyle=val("w:pStyle"),
                    )
                self.abstract[an.get(qn("w:abstractNumId"))] = levels
            for num in root.findall(qn("w:num")):
                ref = num.find(qn("w:abstractNumId"))
                if ref is not None:
                    self.num_to_abstract[num.get(qn("w:numId"))] = ref.get(qn("w:val"))

    @staticmethod
    def _numpr(ppr) -> tuple[str | None, int | None] | None:
        if ppr is None or ppr.numPr is None:
            return None
        n = ppr.numPr
        num_id = str(n.numId.val) if n.numId is not None else None
        ilvl = int(n.ilvl.val) if n.ilvl is not None else None
        return num_id, ilvl

    def resolve(self, paragraph: Paragraph, style) -> tuple[int, str] | None:
        """Return (level, rendered number) or None when the paragraph is not numbered."""
        # numId and ilvl are inherited independently: a style may set only ilvl
        # and take numId from its base style ("סעיף רמה 4" does exactly that).
        num_id: str | None = None
        ilvl: int | None = None
        direct = self._numpr(paragraph._p.pPr)
        if direct:
            num_id, ilvl = direct
        style_id = style.style_id if style is not None else None
        while style is not None and (num_id is None or ilvl is None):
            np_ = self._numpr(style.element.pPr)
            if np_:
                num_id = num_id if num_id is not None else np_[0]
                ilvl = ilvl if ilvl is not None else np_[1]
            style = style.base_style
        if not num_id or num_id == "0":
            return None
        abs_id = self.num_to_abstract.get(num_id)
        levels = self.abstract.get(abs_id or "")
        if not levels:
            return None
        if ilvl is None:
            ilvl = next((i for i, lv in levels.items() if lv.pstyle == style_id), 0)
        level = levels.get(ilvl)
        if level is None or level.fmt in ("bullet", "none") or "%" not in level.text:
            return None

        counters = self.counters.setdefault(abs_id, [0] * 9)
        counters[ilvl] = counters[ilvl] + 1 if counters[ilvl] else level.start
        for deeper in range(ilvl + 1, 9):
            counters[deeper] = 0

        def render(match: re.Match) -> str:
            i = int(match.group(1)) - 1
            lv = levels.get(i, _Level())
            return _format_number(counters[i] or lv.start, lv.fmt)

        number = re.sub(r"%(\d)", render, level.text).strip().rstrip(".")
        return ilvl + 1, number


# --------------------------------------------------------------------------- tables

def _row_cells(row) -> list[str]:
    cells: list[str] = []
    for cell in row.cells:
        text = " ".join(cell.text.split())
        if not cells or cells[-1] != text:  # merged cells are repeated by python-docx
            cells.append(text)
    return cells


def _is_change_log(rows: list[list[str]]) -> bool:
    head = " ".join(" ".join(r) for r in rows[:2])
    return "טבלת שינויים" in head or ("מהדורה" in head and "שינוי" in head)


def _change_log_entries(rows: list[list[str]]) -> list[dict[str, str]]:
    header_idx = next((i for i, r in enumerate(rows) if any("מהדורה" in c for c in r)), None)
    if header_idx is None:
        return []
    header = rows[header_idx]
    entries = []
    for r in rows[header_idx + 1:]:
        if any(r):
            entries.append({header[i] if i < len(header) else str(i): v for i, v in enumerate(r)})
    return entries


def _table_lines(rows: list[list[str]]) -> list[str]:
    rows = [r for r in rows if any(r)]
    if not rows:
        return []
    if len(rows) == 1 or max(len(r) for r in rows) == 1:
        return [" | ".join(c for c in r if c) for r in rows]
    header = rows[0]
    lines = []
    for r in rows[1:]:
        parts = []
        for i, value in enumerate(r):
            if not value:
                continue
            label = header[i] if i < len(header) and header[i] else ""
            parts.append(f"{label}: {value}" if label and label != value else value)
        if parts:
            lines.append(" | ".join(parts))
    return lines


# --------------------------------------------------------------------------- headings

class _StyleCache:
    """python-docx resolves `paragraph.style` with an XPath query on every access,
    which dominated parse time; styles are looked up once per document instead."""

    def __init__(self, document: DocxDocument) -> None:
        self._by_id = {s.style_id: s for s in document.styles}
        try:
            from docx.enum.style import WD_STYLE_TYPE
            self._default = document.styles.default(WD_STYLE_TYPE.PARAGRAPH)
        except Exception:
            self._default = None

    def of(self, paragraph: Paragraph):
        style_id = paragraph._p.style
        return self._by_id.get(style_id, self._default) if style_id else self._default


def _heading_level(paragraph: Paragraph, name: str, text: str, numbered_level: int | None) -> int | None:
    """Return a heading level if the paragraph acts as a heading, else None."""
    if name.startswith("Heading") or name.startswith("כותרת") or name.startswith("כות_"):
        digits = re.findall(r"\d", name)
        return int(digits[0]) if digits else 1
    if name.startswith("נספח"):
        return 1
    if re.search(r"רמה\s*(22|33)$", name):  # unnumbered-looking sub-headings
        return 2 if "22" in name else 3
    short = len(text) <= HEADING_MAX_CHARS and not text.rstrip().endswith((".", ":", ";", ","))
    if numbered_level and short:
        return numbered_level
    # Unstyled documents: a short paragraph whose runs are all bold acts as a heading.
    runs = [r for r in paragraph.runs if r.text.strip()]
    if short and runs and all(r.bold for r in runs):
        return 2
    return None


def _is_toc(style_name: str, text: str) -> bool:
    name = style_name.lower()
    return name.startswith("toc") or "תוכן" in name or bool(_TOC_LINE.search(text))


# --------------------------------------------------------------------------- main

def _iter_body(document: DocxDocument):
    def walk(parent_el):
        for child in parent_el.iterchildren():
            if child.tag == qn("w:p"):
                yield Paragraph(child, document)
            elif child.tag == qn("w:tbl"):
                yield Table(child, document)
            elif child.tag == qn("w:sdt"):
                content = child.find(qn("w:sdtContent"))
                if content is not None:
                    yield from walk(content)
    yield from walk(document.element.body)


def open_docx(source: str | Path | bytes) -> DocxDocument:
    try:
        if isinstance(source, bytes):
            return docx.Document(io.BytesIO(source))
        return docx.Document(str(source))
    except Exception as exc:  # python-docx raises several unrelated types for bad input
        raise ParseError(f"not a readable DOCX: {exc}") from exc


def parse_docx(source: str | Path | bytes) -> ParsedDocument:
    document = open_docx(source)
    numbering = _Numbering(document)
    styles = _StyleCache(document)
    result = ParsedDocument()
    # Each entry: [level, title, has_content]
    path: list[list] = []
    appendix_open = False

    def titles() -> tuple[str, ...]:
        return tuple(entry[1] for entry in path)

    def pop_heading() -> None:
        # A "heading" with nothing under it was really a short content line
        # (e.g. a list item without final punctuation): keep its text searchable.
        level, title, has_content = path[-1]
        parent = tuple(entry[1] for entry in path[:-1])
        path.pop()
        if not has_content:
            result.blocks.append(Block(title, "para", None, parent))
            if path:
                path[-1][2] = True

    def set_heading(level: int, title: str) -> None:
        while path and path[-1][0] >= level:
            pop_heading()
        path.append([level, title, False])

    def add_block(block: Block) -> None:
        result.blocks.append(block)
        for entry in path:
            entry[2] = True

    for item in _iter_body(document):
        if isinstance(item, Table):
            rows = [_row_cells(r) for r in item.rows]
            if _is_change_log(rows):
                result.change_log.extend(_change_log_entries(rows))
                continue
            for line in _table_lines(rows):
                add_block(Block(line, "table", None, titles()))
            continue

        raw = item.text
        text = " ".join(raw.split())
        style = styles.of(item)
        name = style.name if style is not None else ""
        if not text or _is_toc(name, raw):
            continue
        resolved = numbering.resolve(item, style)
        number, numbered_level = (resolved[1], resolved[0]) if resolved else (None, None)

        # Appendix title is split over two paragraphs: "נספח א" + "הגדרות".
        if name.startswith("נספח - כותרת"):
            set_heading(1, text)
            appendix_open = True
            continue
        if name.startswith("נספח - תיאור") and appendix_open and path:
            path[-1][1] = f"{path[-1][1]} - {text}"
            appendix_open = False
            continue
        appendix_open = False

        level = _heading_level(item, name, text, numbered_level)
        if level is not None:
            set_heading(level, f"{number} {text}" if number else text)
            continue
        # A numbered section at level L closes any open heading at level >= L (its
        # siblings). Unnumbered paragraphs (numId=0) continue the open heading.
        if numbered_level:
            while path and path[-1][0] >= numbered_level:
                pop_heading()
        add_block(Block(text, "para", number, titles()))
    while path:
        pop_heading()
    return result
