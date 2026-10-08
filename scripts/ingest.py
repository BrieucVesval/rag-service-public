"""Convert raw Service-Public XML fiches into normalized Markdown Documents.

Reads data/raw/service_public/*.xml, skips excluded fiche types (guided searches),
and writes one JSON Document per fiche to data/processed/service_public/<ID>.json,
plus a manifest.json recording the raw snapshot used, counts and excluded fiches.

Usage:
    uv run python scripts/ingest.py
    uv run python scripts/ingest.py --overwrite   # regenerate an existing output
"""

import argparse
import json
import logging
import statistics
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from defusedxml import ElementTree as ET

from rag.ingestion.service_public import fiche_to_document

# Decision trees of ~10k words that overlap other fiches; excluded from v1 (see project log).
EXCLUDED_TYPES = frozenset({"Recherche guidée"})
RAW_MANIFEST = "manifest.json"


class WarningCounter(logging.Handler):
    """Counts warnings emitted while parsing, so schema drift shows up in the summary."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.count = 0

    def emit(self, record: logging.LogRecord) -> None:
        self.count += 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw", type=Path, default=Path("data/raw/service_public"))
    parser.add_argument("--out", type=Path, default=Path("data/processed/service_public"))
    parser.add_argument(
        "--overwrite", action="store_true", help="Replace existing processed JSON files"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    warnings = WarningCounter()
    logging.getLogger().addHandler(warnings)

    existing = sorted(args.out.glob("*.json")) if args.out.exists() else []
    if existing and not args.overwrite:
        print(f"{args.out} is not empty; pass --overwrite to regenerate it.", file=sys.stderr)
        return 1
    # Remove stale outputs so fiches deleted upstream do not linger.
    for path in existing:
        path.unlink()
    args.out.mkdir(parents=True, exist_ok=True)

    types: Counter[str] = Counter()
    excluded: list[str] = []
    word_counts: list[tuple[int, str]] = []
    for path in sorted(args.raw.glob("*.xml")):
        root = ET.fromstring(path.read_bytes())
        fiche_type = root.get("type") or "unknown"
        if fiche_type in EXCLUDED_TYPES:
            excluded.append(path.stem)
            continue
        document = fiche_to_document(root)
        (args.out / f"{document.doc_id}.json").write_text(
            document.model_dump_json(indent=2), encoding="utf-8"
        )
        types[fiche_type] += 1
        word_counts.append((len(document.text.split()), document.doc_id))

    if not word_counts:
        print(f"No fiche found in {args.raw}", file=sys.stderr)
        return 1

    raw_manifest_path = args.raw / RAW_MANIFEST
    raw_manifest = json.loads(raw_manifest_path.read_text()) if raw_manifest_path.exists() else {}
    manifest = {
        "processed_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "raw_dir": str(args.raw),
        "raw_downloaded_at": raw_manifest.get("downloaded_at"),
        "excluded_types": sorted(EXCLUDED_TYPES),
        "document_count": len(word_counts),
        "documents_by_type": dict(types.most_common()),
        "excluded_count": len(excluded),
        "excluded": excluded,
        "parser_warnings": warnings.count,
    }
    (args.out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))

    word_counts.sort()
    lengths = [count for count, _ in word_counts]
    print(f"Wrote {len(word_counts)} documents to {args.out}")
    for fiche_type, count in types.most_common():
        print(f"  {count:4d}  {fiche_type}")
    print(f"Excluded {len(excluded)} fiches of type {', '.join(sorted(EXCLUDED_TYPES))}")
    print(
        f"Words per document: min {lengths[0]} ({word_counts[0][1]}), "
        f"median {statistics.median(lengths):.0f}, "
        f"max {lengths[-1]} ({word_counts[-1][1]}), total {sum(lengths)}"
    )
    print(f"Parser warnings: {warnings.count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
