"""Download the Service-Public.gouv.fr "Particuliers" XML feed and extract one theme.

Source: https://www.data.gouv.fr/datasets/fiches-pratiques-et-ressources-de-service-public-gouv-fr-particuliers
License: Licence Ouverte / Open Licence 2.0 (attribution required).

Only the "F" files (practical fiches: information sheets, Q&A, guided searches)
whose Dublin Core `subject` contains the requested theme are kept, untouched.
A manifest.json records source URL, download date and file list for reproducibility.

Usage:
    python scripts/fetch_corpus.py --theme Logement
"""

import argparse
import io
import json
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import UTC, datetime
from pathlib import Path

FEED_URL = "https://lecomarquage.service-public.gouv.fr/vdd/3.5/part/zip/vosdroits-latest.zip"
SCHEMA_VERSION = "3.5"
DATASET_URL = (
    "https://www.data.gouv.fr/datasets/"
    "fiches-pratiques-et-ressources-de-service-public-gouv-fr-particuliers"
)
DC = "{http://purl.org/dc/elements/1.1/}"


def download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def fiche_subjects(xml_bytes: bytes) -> list[str]:
    root = ET.fromstring(xml_bytes)
    subject = root.findtext(f"{DC}subject") or ""
    return [s.strip() for s in subject.split(",") if s.strip()]


def is_fiche(name: str) -> bool:
    filename = Path(name).name
    return filename.startswith("F") and filename.endswith(".xml") and filename[1:2].isdigit()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--theme", default="Logement", help="Theme to keep (dc:subject)")
    parser.add_argument("--out", type=Path, default=Path("data/raw/service_public"))
    args = parser.parse_args()

    if args.out.exists() and any(args.out.iterdir()):
        print(f"{args.out} is not empty; refusing to overwrite raw data.", file=sys.stderr)
        return 1

    print(f"Downloading {FEED_URL} ...")
    archive = download(FEED_URL)
    downloaded_at = datetime.now(UTC).isoformat(timespec="seconds")

    kept: list[str] = []
    args.out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        for name in zf.namelist():
            if not is_fiche(name):
                continue
            content = zf.read(name)
            if args.theme in fiche_subjects(content):
                filename = Path(name).name
                (args.out / filename).write_bytes(content)
                kept.append(filename)

    manifest = {
        "source": DATASET_URL,
        "feed_url": FEED_URL,
        "schema_version": SCHEMA_VERSION,
        "license": "Licence Ouverte / Open Licence 2.0",
        "producer": "Direction de l'information légale et administrative (DILA)",
        "downloaded_at": downloaded_at,
        "theme": args.theme,
        "file_count": len(kept),
        "files": sorted(kept),
    }
    (args.out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(f"Kept {len(kept)} fiches for theme '{args.theme}' in {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
