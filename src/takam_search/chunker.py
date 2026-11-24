"""Group parsed blocks into retrieval chunks.

A chunk is a run of consecutive blocks under the same heading, up to MAX_CHARS.
The heading path is prepended so the chunk is understandable (and searchable) on
its own. Documents without structure fall back to size-only grouping.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .parser import Block, ParsedDocument

MAX_CHARS = 1000
LONG_BLOCK_OVERLAP_SENTENCES = 1
_SENTENCE_END = re.compile(r"(?<=[.!?;:])\s+")


@dataclass
class Chunk:
    ordinal: int
    text: str  # heading path + body, as indexed and shown
    body: str
    heading_path: str
    section: str | None  # first section number in the chunk
    section_end: str | None  # last section number, when the chunk spans several


def _block_line(block: Block) -> str:
    return f"{block.number} {block.text}" if block.number else block.text


def _split_long(block: Block, max_chars: int) -> list[Block]:
    """Split an over-long paragraph into windows of sentences with a 1-sentence overlap."""
    sentences = [s for s in _SENTENCE_END.split(block.text) if s.strip()]
    if len(sentences) <= 1:
        # No sentence boundaries: hard split on characters.
        step = max_chars - 100
        pieces = [block.text[i:i + max_chars] for i in range(0, len(block.text), step)]
    else:
        pieces, current = [], []
        for sentence in sentences:
            if current and len(" ".join(current + [sentence])) > max_chars:
                pieces.append(" ".join(current))
                current = current[-LONG_BLOCK_OVERLAP_SENTENCES:]
            current.append(sentence)
        if current:
            pieces.append(" ".join(current))
    return [Block(p, block.kind, block.number, block.heading_path) for p in pieces]


def chunk_document(parsed: ParsedDocument, max_chars: int = MAX_CHARS) -> list[Chunk]:
    units: list[Block] = []
    for block in parsed.blocks:
        units.extend(_split_long(block, max_chars) if len(_block_line(block)) > max_chars else [block])

    chunks: list[Chunk] = []
    group: list[Block] = []

    def flush() -> None:
        if not group:
            return
        path = " > ".join(group[0].heading_path)
        body = "\n".join(_block_line(b) for b in group)
        numbers = [b.number for b in group if b.number]
        chunks.append(
            Chunk(
                ordinal=len(chunks),
                text=f"{path}\n{body}" if path else body,
                body=body,
                heading_path=path,
                section=numbers[0] if numbers else None,
                section_end=numbers[-1] if len(numbers) > 1 else None,
            )
        )
        group.clear()

    size = 0
    for unit in units:
        line_len = len(_block_line(unit)) + 1
        same_heading = group and unit.heading_path == group[0].heading_path
        if group and (not same_heading or size + line_len > max_chars):
            flush()
            size = 0
        group.append(unit)
        size += line_len
    flush()
    return chunks
