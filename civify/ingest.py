"""Turn a folder of downloaded PDFs for one agenda item into `item.json`.

Usage:
    python -m civify.ingest data/2026.TE34.21 --retrieved 2026-11-13

The output lists every file with its type, author, page count, checksum and the
fields read from it. Nothing here is inferred by a model; it is what the
documents say about themselves. Staff review and correct it before publishing.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from civify.classify import DocType, classify
from civify.extract import extract


def ingest(folder: Path, retrieved: str) -> dict:
    docs = []
    for pdf in sorted(folder.glob("*.pdf")):
        doc = extract(pdf)
        c = classify(doc)
        docs.append({
            "filename": doc.filename,
            "sha256": doc.sha256,
            "pages": len(doc.pages),
            "doc_type": c.doc_type.value,
            "author": c.author,
            "evidence": c.evidence,
            "fields": c.fields,
        })
    item_id = next((d["fields"]["item_id"] for d in docs if d["doc_type"] == DocType.ITEM_PAGE.value), folder.name)
    return {"item_id": item_id, "retrieved": retrieved, "source_folder": str(folder), "documents": docs}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path)
    # Required on purpose: a defaulted date would silently record the wrong provenance.
    ap.add_argument("--retrieved", required=True, help="date the files were downloaded (YYYY-MM-DD)")
    args = ap.parse_args()
    result = ingest(args.folder, args.retrieved)
    out = args.folder / "item.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    for d in result["documents"]:
        print(f"{d['doc_type']:24} {d['filename']:32} {d['pages']:3} pp  {d['author'] or '-'}")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
