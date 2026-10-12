"""Header-based chunking: cut a Markdown document along its heading tree.

The loader renders fiches as Markdown where chapters, situations and conditional
cases ("Cas : ...") are headings, so the subtree under a heading is a coherent unit:
a rule stays with the condition it applies to.

For a section (a heading and everything below it, up to the next heading of the
same or a higher level):
- if the whole section fits in `max_size` characters, it is one chunk;
- otherwise its own text (heading and paragraphs before its first sub-heading) and
  its sub-sections are packed in order into chunks of at most `max_size`, without
  mixing two branches of the tree; a sub-section that does not fit is chunked the
  same way, recursively;
- own text that alone exceeds `max_size` is split at blank lines; an oversized table
  is split by rows with its caption and header row repeated, so every row still
  reads on its own; a single paragraph still too long falls back to fixed-size
  windows with overlap.

Each chunk records its heading path (the headings above it, outermost first). With
prefix "path" the path is prepended to the chunk text, so a passage under
"Cas : En cas de violences" still says which fiche, chapter and case it belongs to;
with "none" the text is the passage alone (ablation of the prefix).
"""

import re
from dataclasses import dataclass, field, replace
from typing import Literal

from rag.chunking.base import make_chunk_id
from rag.chunking.fixed import FixedSizeChunker, trim_span
from rag.models import Chunk, Document

HeadingPrefix = Literal["path", "none"]

PATH_SEPARATOR = " > "

_HEADING = re.compile(r"^(#{1,6})[ \t]+(\S[^\n]*?)[ \t]*$", re.MULTILINE)
_BLANK_LINE = re.compile(r"\n[ \t]*\n")
_TABLE_SEPARATOR = re.compile(r"^\|[\s:|-]+\|$")
_CAPTION = re.compile(r"^\*\*[^\n]+\*\*$")


@dataclass
class _Section:
    level: int  # 0 for the virtual root holding the whole document
    title: str | None
    start: int
    end: int
    children: list["_Section"] = field(default_factory=list)

    @property
    def own_end(self) -> int:
        """End of the section's own text, i.e. start of its first sub-section."""
        return self.children[0].start if self.children else self.end


@dataclass(frozen=True)
class _Piece:
    start: int
    end: int
    path: tuple[str, ...]
    context: str = ""  # text repeated before the passage (table caption and header)


class HeaderChunker:
    name = "headers"

    def __init__(self, max_size: int, overlap: int, prefix: HeadingPrefix = "path") -> None:
        # Validates the sizes and splits paragraphs longer than max_size.
        self._fallback = FixedSizeChunker(max_size, overlap)
        self.max_size = max_size
        self.overlap = overlap
        self.prefix = prefix
        self.label = f"{self.name}-{prefix}"

    def chunk(self, document: Document) -> list[Chunk]:
        text = document.text
        chunks: list[Chunk] = []
        for piece in self._section_pieces(text, parse_sections(text), ()):
            start, end = trim_span(text, piece.start, piece.end)
            if start >= end:
                continue
            path = PATH_SEPARATOR.join(piece.path)
            parts = [path] if self.prefix == "path" and path else []
            if piece.context:
                parts.append(piece.context)
            parts.append(text[start:end])
            chunks.append(
                Chunk(
                    chunk_id=make_chunk_id(document.doc_id, self.name, len(chunks)),
                    doc_id=document.doc_id,
                    text="\n\n".join(parts),
                    strategy=self.name,
                    position=len(chunks),
                    start_char=start,
                    end_char=end,
                    doc_title=document.title,
                    url=document.url,
                    heading_path=path or None,
                )
            )
        return chunks

    def _fits(self, text: str, start: int, end: int) -> bool:
        trimmed_start, trimmed_end = trim_span(text, start, end)
        return trimmed_end - trimmed_start <= self.max_size

    def _section_pieces(self, text: str, section: _Section, path: tuple[str, ...]) -> list[_Piece]:
        if self._fits(text, section.start, section.end):
            return [_Piece(section.start, section.end, path)]
        # Path of the pieces that do not contain this section's heading line.
        inner = (*path, section.title) if section.title else path
        units: list[tuple[int, int, _Section | None]] = []
        if text[section.start : section.own_end].strip():
            units.append((section.start, section.own_end, None))
        units += [(child.start, child.end, child) for child in section.children]

        pieces: list[_Piece] = []
        # Consecutive spans packed into the next chunk.
        group: list[tuple[int, int]] = []

        def group_piece() -> _Piece:
            # A group that starts at the heading line keeps the path above the section.
            group_path = path if group[0][0] == section.start else inner
            return _Piece(group[0][0], group[-1][1], group_path)

        for start, end, child in units:
            if self._fits(text, start, end):
                if group and not self._fits(text, group[0][0], end):
                    pieces.append(group_piece())
                    group = []
                group.append((start, end))
                continue
            if child is None:
                own_pieces = self._own_text_pieces(text, start, end, path, inner)
                pieces += own_pieces[:-1]
                last = own_pieces[-1]
                # The tail of the own text may still join what follows (see below).
                if last.context:
                    pieces.append(last)
                else:
                    group = [(last.start, last.end)]
                continue
            child_pieces = self._section_pieces(text, child, inner)
            first = child_pieces[0]
            if group and not first.context and self._fits(text, group[0][0], first.end):
                # A short lead (e.g. a heading and its intro sentence) joins the start of
                # the next sub-section instead of becoming a chunk of its own.
                child_pieces[0] = _Piece(group[0][0], first.end, group_piece().path)
            elif group:
                pieces.append(group_piece())
            group = []
            pieces += child_pieces
        if group:
            pieces.append(group_piece())
        return pieces

    def _own_text_pieces(
        self, text: str, start: int, end: int, path: tuple[str, ...], inner: tuple[str, ...]
    ) -> list[_Piece]:
        """Split a section's own text, too long for one chunk, at blank lines."""
        pieces: list[_Piece] = []
        group_start: int | None = None
        group_end = start
        for block_start, block_end in _blocks(text, start, end):
            if block_end - block_start <= self.max_size:
                if group_start is not None and block_end - group_start > self.max_size:
                    pieces.append(_Piece(group_start, group_end, inner))
                    group_start = None
                if group_start is None:
                    group_start = block_start
                group_end = block_end
            else:
                table_start = _table_start(text, block_start, block_end)
                if table_start is not None:
                    block_pieces = self._table_pieces(
                        text, block_start, table_start, block_end, inner
                    )
                else:
                    block_pieces = [
                        _Piece(block_start + a, block_start + b, inner)
                        for a, b in self._fallback.windows(text[block_start:block_end])
                    ]
                first = block_pieces[0]
                if group_start is not None:
                    if not first.context and first.end - group_start <= self.max_size:
                        # Short lead (e.g. the heading line) joins the start of the block.
                        block_pieces[0] = _Piece(group_start, first.end, inner)
                    else:
                        pieces.append(_Piece(group_start, group_end, inner))
                    group_start = None
                pieces += block_pieces
        if group_start is not None:
            pieces.append(_Piece(group_start, group_end, inner))
        # The first piece starts with the section's heading line: its path stops above it.
        if pieces:
            pieces[0] = replace(pieces[0], path=path)
        return pieces

    def _table_pieces(
        self, text: str, start: int, table_start: int, end: int, path: tuple[str, ...]
    ) -> list[_Piece]:
        """Split a table (with its caption, if any) by rows.

        The first piece holds the caption and header row; later pieces repeat them.
        """
        lines = _lines(text, table_start, end)
        header_count = 2 if len(lines) > 2 and _TABLE_SEPARATOR.match(text[slice(*lines[1])]) else 1
        header_end = lines[header_count - 1][1]
        header = text[start:header_end]
        pieces: list[_Piece] = []
        piece_start, piece_end, has_rows = start, header_end, False
        context = ""  # the first piece contains the caption and header row themselves
        for row_start, row_end in lines[header_count:]:
            if len(header) + 2 + row_end - row_start > self.max_size:
                if has_rows:
                    pieces.append(_Piece(piece_start, piece_end, path, context))
                pieces += self._long_row_pieces(text, row_start, row_end, header, path)
                piece_start, piece_end, has_rows, context = row_end, row_end, False, header
                continue
            size = row_end - piece_start + (len(context) + 2 if context else 0)
            if has_rows and size > self.max_size:
                pieces.append(_Piece(piece_start, piece_end, path, context))
                piece_start, context = row_start, header
            piece_end, has_rows = row_end, True
        pieces.append(_Piece(piece_start, piece_end, path, context))
        return pieces

    def _long_row_pieces(
        self, text: str, start: int, end: int, header: str, path: tuple[str, ...]
    ) -> list[_Piece]:
        """Split a single table row longer than a chunk; each window repeats the header."""
        budget = max(self.max_size - len(header) - 2, self.max_size // 2)
        windows = FixedSizeChunker(budget, min(self.overlap, budget // 2)).windows(text[start:end])
        return [_Piece(start + a, start + b, path, header) for a, b in windows]


def parse_sections(text: str) -> _Section:
    """Heading tree of a Markdown text, under a virtual root covering the whole text."""
    root = _Section(level=0, title=None, start=0, end=len(text))
    stack = [root]
    for match in _HEADING.finditer(text):
        level = len(match.group(1))
        while stack[-1].level >= level:
            stack.pop().end = match.start()
        section = _Section(level=level, title=match.group(2), start=match.start(), end=len(text))
        stack[-1].children.append(section)
        stack.append(section)
    return root


def _blocks(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Non-empty spans separated by blank lines, trimmed; a table keeps its caption."""
    spans: list[tuple[int, int]] = []
    position = start
    for match in _BLANK_LINE.finditer(text, start, end):
        spans.append(trim_span(text, position, match.start()))
        position = match.end()
    spans.append(trim_span(text, position, end))
    blocks: list[tuple[int, int]] = []
    for span in (span for span in spans if span[0] < span[1]):
        previous = text[slice(*blocks[-1])] if blocks else ""
        if _CAPTION.match(previous) and _is_table(text[slice(*span)]):
            blocks[-1] = (blocks[-1][0], span[1])
        else:
            blocks.append(span)
    return blocks


def _lines(text: str, start: int, end: int) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    position = start
    while position < end:
        newline = text.find("\n", position, end)
        line_end = end if newline == -1 else newline
        spans.append((position, line_end))
        position = line_end + 1
    return spans


def _is_table(block: str) -> bool:
    return all(line.startswith("|") for line in block.splitlines())


def _table_start(text: str, start: int, end: int) -> int | None:
    """Start of the table in a block made of a table, optionally after its caption."""
    if _is_table(text[start:end]):
        return start
    caption_end = text.find("\n", start, end)
    if caption_end == -1 or not _CAPTION.match(text[start:caption_end]):
        return None
    table_start, _ = trim_span(text, caption_end, end)
    return table_start if _is_table(text[table_start:end]) else None
