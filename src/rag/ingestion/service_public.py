"""Parse Service-Public.gouv.fr XML fiches (schema v3.5) into Markdown Documents.

The body is rendered to Markdown so that structure survives into chunking:
sections become headings, conditional cases ("Cas") become headings too, so a
rule always stays attached to the situation it applies to (e.g. Paris vs. other
communes). Navigation, related links and questionnaire logic are dropped.

The schema evolves daily: unknown elements never raise. Their text is kept and a
warning is logged so the renderer can be extended deliberately.
"""

import logging
import re
from collections.abc import Iterable
from datetime import date
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as ET

from rag.models import Document

logger = logging.getLogger(__name__)

SOURCE = "service_public"
DC = "{http://purl.org/dc/elements/1.1/}"
MAX_HEADING_LEVEL = 6
CASE_PREFIX = "Cas : "
WHERE_TO_GO_PREFIX = "Où s'adresser : "
ONLINE_SERVICE_PREFIX = "Service en ligne : "

# Table layout: merged cells (HTML colspan / rowspan) and multi-row headers.
COLSPAN_ATTR = "fusionHorizontale"
ROWSPAN_ATTR = "fusionVerticale"
HEADER_ROW_TYPE = "header"
HEADER_LABEL_SEPARATOR = " – "

# Top-level children of <Publication> that hold the answer content, rendered in this order.
BODY_TAGS = ("Avertissement", "Introduction", "Texte", "ListeSituations")

# Top-level children that are metadata, navigation or links to other fiches.
IGNORED_TOP_LEVEL_TAGS = frozenset(
    {
        "SurTitre",
        "Audience",
        "Canal",
        "FilDAriane",
        "Theme",
        "SousThemePere",
        "DossierPere",
        "Definition",
        "Abreviation",
        "Reference",
        "ServiceEnLigne",
        "QuestionReponse",
        "PourEnSavoirPlus",
        "QuiPeutMAider",
        "VoirAussi",
        "CommentFaireSi",
        "RechercheGuideePere",
        "RechercheGuidee",
        "FicheConnexe",
        "Questionnaire",
        "OuSAdresser",
        "FicheSuivante",
        "FichePrecedente",
    }
)

# Elements whose <Titre> becomes a Markdown heading, one level deeper than their parent.
SECTION_TAGS = frozenset({"Chapitre", "SousChapitre", "Situation", "Cas"})

# Boxed notes rendered as blockquotes headed by their <Titre> ("À savoir", "Attention"...).
CALLOUT_TAGS = frozenset(
    {"ASavoir", "Attention", "ANoter", "Rappel", "Exemple", "Complement", "Avertissement", "Aide"}
)

# Wrappers without content of their own: their children are rendered in order.
CONTAINER_TAGS = frozenset(
    {"Texte", "Introduction", "FragmentConditionne", "ListeSituations", "BlocCas"}
)

# Titles (read by their parent), questionnaire logic, media and layout hints.
SKIPPED_TAGS = frozenset(
    {
        "Titre",
        "TitreRiche",
        "TitreAlternatif",
        "Condition",
        "Video",
        "Infographie",
        "PourEnSavoirPlus",
        "Colonne",
    }
)

_WHITESPACE = re.compile(r"\s+")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def parse_fiche(xml: bytes) -> Document:
    """Parse the raw bytes of one fiche into a Document."""
    return fiche_to_document(ET.fromstring(xml))


def fiche_to_document(root: Element) -> Document:
    """Convert a parsed <Publication> element into a Document."""
    doc_id = root.get("ID")
    if not doc_id:
        raise ValueError("Publication element has no ID attribute")

    title = _inline(root.find(f"{DC}title"))
    _warn_unknown_top_level(root, doc_id)
    blocks = [f"# {title}"]
    for tag in BODY_TAGS:
        for element in root.findall(tag):
            blocks.extend(_render_block(element, level=2, doc_id=doc_id))

    return Document(
        doc_id=doc_id,
        source=SOURCE,
        title=title,
        text="\n\n".join(blocks),
        url=root.get("spUrl"),
        doc_type=root.get("type"),
        modified_at=_parse_modified(root.findtext(f"{DC}date")),
        breadcrumb=[_inline(level) for level in root.findall("FilDAriane/Niveau")],
        themes=_split_subjects(root.findtext(f"{DC}subject")),
        description=_inline(root.find(f"{DC}description")) or None,
    )


def _warn_unknown_top_level(root: Element, doc_id: str) -> None:
    for child in root:
        known = child.tag in BODY_TAGS or child.tag in IGNORED_TOP_LEVEL_TAGS
        if not known and not child.tag.startswith(DC):
            logger.warning("Unknown top-level element <%s> in %s, ignored", child.tag, doc_id)


def _render_children(element: Element, level: int, doc_id: str) -> list[str]:
    blocks: list[str] = []
    for child in element:
        blocks.extend(_render_block(child, level, doc_id))
    return blocks


def _render_block(element: Element, level: int, doc_id: str) -> list[str]:
    """Render one block-level element to a list of Markdown blocks."""
    tag = element.tag
    if tag in SKIPPED_TAGS:
        return []
    if tag == "Paragraphe":
        return _non_empty(_inline(element))
    if tag == "TitreFlottant":
        text = _inline(element)
        return [f"**{text}**"] if text else []
    if tag == "Liste":
        return _non_empty(_render_list(element))
    if tag == "Tableau":
        return _non_empty(_render_table(element))
    if tag in SECTION_TAGS:
        return _render_section(element, level, doc_id)
    if tag in CALLOUT_TAGS:
        return _non_empty(_render_callout(element, level, doc_id))
    if tag == "OuSAdresser":
        return _non_empty(_prefixed_title(WHERE_TO_GO_PREFIX, element))
    if tag == "ServiceEnLigne":
        return _non_empty(_prefixed_title(ONLINE_SERVICE_PREFIX, element))
    if tag in CONTAINER_TAGS:
        return _render_children(element, level, doc_id)
    logger.warning("Unknown element <%s> in %s, kept as plain text", tag, doc_id)
    return _non_empty(_inline(element))


def _render_section(element: Element, level: int, doc_id: str) -> list[str]:
    title = _inline(element.find("Titre"))
    if element.tag == "Cas":
        title = f"{CASE_PREFIX}{title}"
    heading = f"{'#' * min(level, MAX_HEADING_LEVEL)} {title}"
    return [heading, *_render_children(element, level + 1, doc_id)]


def _render_callout(element: Element, level: int, doc_id: str) -> str:
    title = _inline(element.find("Titre"))
    blocks = _render_children(element, level, doc_id)
    if title:
        blocks.insert(0, f"**{title}**")
    lines = "\n\n".join(blocks).splitlines()
    return "\n".join(f"> {line}" if line else ">" for line in lines)


def _render_list(element: Element, indent: int = 0) -> str:
    numbered = element.get("type") == "numero"
    lines: list[str] = []
    for index, item in enumerate(element.findall("Item"), start=1):
        marker = f"{index}." if numbered else "-"
        text = " ".join(_non_empty_all(_inline(p) for p in item.findall("Paragraphe")))
        lines.append(f"{'  ' * indent}{marker} {text}")
        lines.extend(_render_list(sub, indent + 1) for sub in item.findall("Liste"))
    return "\n".join(lines)


def _render_table(element: Element) -> str:
    grid = _table_grid(element)
    if not grid:
        return ""
    width = max(len(cells) for _, cells in grid)
    rows = [cells + [""] * (width - len(cells)) for _, cells in grid]

    # Markdown allows a single header row: leading header rows are merged column by column.
    # Without a typed header, the first row plays that role.
    header_count = next((i for i, (is_header, _) in enumerate(grid) if not is_header), len(grid))
    header_count = max(header_count, 1)
    header = [_merge_labels(column) for column in zip(*rows[:header_count], strict=True)]

    lines: list[str] = []
    caption = _inline(element.find("TitreRiche"))
    if caption:
        lines += [f"**{caption}**", ""]
    lines.append(_table_row(header))
    lines.append(_table_row(["---"] * width))
    lines.extend(_table_row(row) for row in rows[header_count:])
    return "\n".join(lines)


def _table_grid(element: Element) -> list[tuple[bool, list[str]]]:
    """Lay out a table's cells on a grid, as (is_header, cells) rows.

    Merged cells follow HTML semantics: cells covered by a span are absent from the XML.
    The merged cell's text is repeated in every position it covers, so each row reads on
    its own, even when a chunk boundary falls inside the table.
    """
    grid: list[tuple[bool, list[str]]] = []
    carried: dict[int, tuple[str, int]] = {}  # column -> (text, rows still covered below)
    for row in element.findall("Rangée"):
        cells = {column: text for column, (text, _) in carried.items()}
        carried = {column: (text, left - 1) for column, (text, left) in carried.items() if left > 1}
        column = 0
        for cell in row.findall("Cellule"):
            while column in cells:
                column += 1
            text = _cell_text(cell)
            colspan, rowspan = _span(cell, COLSPAN_ATTR), _span(cell, ROWSPAN_ATTR)
            for covered in range(column, column + colspan):
                cells[covered] = text
                if rowspan > 1:
                    carried[covered] = (text, rowspan - 1)
            column += colspan
        if row.find("Cellule") is None:
            continue
        is_header = row.get("type") == HEADER_ROW_TYPE
        grid.append((is_header, [cells.get(i, "") for i in range(max(cells) + 1)]))
    return grid


def _span(cell: Element, attribute: str) -> int:
    value = cell.get(attribute, "")
    return max(int(value), 1) if value.isdigit() else 1


def _merge_labels(labels: Iterable[str]) -> str:
    """Join the distinct non-empty labels of one header column, top to bottom."""
    return HEADER_LABEL_SEPARATOR.join(dict.fromkeys(_non_empty_all(labels)))


def _table_row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _cell_text(cell: Element) -> str:
    parts: list[str] = []
    for child in cell:
        if child.tag == "Liste":
            parts.extend(_inline(item) for item in child.iter("Item"))
        else:
            parts.append(_inline(child))
    return " ; ".join(_non_empty_all(parts)).replace("|", "\\|")


def _prefixed_title(prefix: str, element: Element) -> str:
    title = _inline(element.find("Titre"))
    return f"{prefix}{title}" if title else ""


def _inline(element: Element | None) -> str:
    """Flatten an element's text, dropping inline markup (links, emphasis, superscripts)."""
    if element is None:
        return ""
    return _WHITESPACE.sub(" ", "".join(element.itertext())).strip()


def _non_empty(text: str) -> list[str]:
    return [text] if text else []


def _non_empty_all(texts: Iterable[str]) -> list[str]:
    return [text for text in texts if text]


def _parse_modified(value: str | None) -> date | None:
    match = _ISO_DATE.search(value or "")
    return date.fromisoformat(match.group()) if match else None


def _split_subjects(value: str | None) -> list[str]:
    return [subject.strip() for subject in (value or "").split(",") if subject.strip()]
