"""Upload and validate PDFs before anything is processed.

Files land in a staging folder (data/_uploads/<upload id>/) and are checked one
by one: is it really a PDF, how many pages, does it have text or need OCR, what
kind of City record is it, and is it a duplicate or a new version of something
already on file. A file only counts as uploaded once it has passed validation.
Nothing moves into an item folder until a worker starts processing.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import shutil
from pathlib import Path

from civify import db
from civify.classify import DocType, classify
from civify.extract import extract

MAX_BYTES = 60 * 1024 * 1024
ITEM_ID = re.compile(r"^\d{4}\.[A-Z]{2,4}\d+\.\d+$")


def uploads_root() -> Path:
    return db.DATA / "_uploads"


def new_upload() -> str:
    uid = secrets.token_hex(6)
    (uploads_root() / uid).mkdir(parents=True)
    return uid


def folder(upload_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{12}", upload_id):
        raise ValueError("bad upload id")
    return uploads_root() / upload_id


def safe_name(name: str) -> str:
    base = re.sub(r"[^\w.\- ]", "_", Path(name or "file.pdf").name).strip() or "file.pdf"
    return base if base.lower().endswith(".pdf") else base + ".pdf"


def existing_files() -> dict[str, str]:
    """sha256 -> 'item/filename' for every PDF already in an item folder."""
    out = {}
    for pdf in db.DATA.glob("*/*.pdf"):
        if pdf.parent.name.startswith("_"):
            continue
        out[hashlib.sha256(pdf.read_bytes()).hexdigest()] = f"{pdf.parent.name}/{pdf.name}"
    return out


def validate_file(path: Path, known: dict[str, str], staged: dict[str, str]) -> dict:
    data = path.read_bytes()
    info = {"filename": path.name, "size": len(data), "pages": None, "doc_type": None, "author": None,
            "fields": {}, "needs_ocr": False, "warnings": [], "state": "valid", "error": None}
    sha = hashlib.sha256(data).hexdigest()
    info["sha256"] = sha
    if len(data) > MAX_BYTES:
        return {**info, "state": "invalid", "error": f"larger than {MAX_BYTES // 1024 // 1024} MB"}
    if not data.startswith(b"%PDF"):
        return {**info, "state": "invalid", "error": "not a PDF file"}
    try:
        doc = extract(path)
    except Exception as e:
        return {**info, "state": "invalid", "error": f"PDF could not be read ({type(e).__name__})"}
    c = classify(doc)
    info.update(pages=len(doc.pages), doc_type=c.doc_type.value, author=c.author, fields=c.fields)
    if not any(p.text.strip() for p in doc.pages):
        info["needs_ocr"] = True
        info["warnings"].append("no text could be read; it may be a scan that needs OCR")
    if c.doc_type is DocType.UNKNOWN and not info["needs_ocr"]:
        info["warnings"].append("not recognised as a City record type; it will be kept but not used for drafting")
    if sha in known:
        info["warnings"].append(f"identical to {known[sha]}, already on file")
    if sha in staged and staged[sha] != path.name:
        info["warnings"].append(f"identical to {staged[sha]} in this upload")
    return info


def validate(upload_id: str) -> dict:
    """Re-validate every file in the upload and write manifest.json."""
    base = folder(upload_id)
    known = existing_files()
    staged: dict[str, str] = {}
    files = []
    for pdf in sorted(base.glob("*.pdf")):
        info = validate_file(pdf, known, staged)
        staged.setdefault(info["sha256"], pdf.name)
        files.append(info)
    meta = load(upload_id).get("meta", {})
    detected = next((f["fields"].get("item_id") for f in files if f["doc_type"] == DocType.ITEM_PAGE.value), None)
    item_id = meta.get("item_id") or detected
    reports = [f for f in files if f["doc_type"] == DocType.STAFF_REPORT.value]
    if item_id and reports:
        existing = [d for d in (db.load_item(item_id) or {}).get("documents", []) if d["doc_type"] == "staff_report"]
        for r in reports:
            if existing and r["sha256"] not in {d["sha256"] for d in existing}:
                r["warnings"].append(f"a new version of the staff report (dated {r['fields'].get('Date') or 'unknown'}); "
                                     f"the item already has {len(existing)}. The newest dated report is used for drafting.")
    problems = []
    valid = [f for f in files if f["state"] == "valid"]
    if not valid:
        problems.append("Add at least one valid PDF.")
    if not item_id:
        problems.append("Enter the agenda item number (e.g. 2027.PB1.6), or include the saved item page so it can be read from it.")
    elif not ITEM_ID.match(item_id):
        problems.append(f"'{item_id}' doesn't look like an agenda item number (e.g. 2027.PB1.6).")
    has_report = bool(reports) or any(d["doc_type"] == "staff_report" for d in (db.load_item(item_id) or {}).get("documents", [])) if item_id else bool(reports)
    has_page = any(f["doc_type"] == DocType.ITEM_PAGE.value for f in files)
    if not has_report and not has_page:
        problems.append("Include the staff report, or the saved item page so linked reports can be fetched.")
    manifest = {"upload_id": upload_id, "files": files, "meta": meta, "detected_item_id": detected,
                "item_id": item_id, "ready": not problems, "problems": problems}
    (base / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return manifest


def load(upload_id: str) -> dict:
    p = folder(upload_id) / "manifest.json"
    return json.loads(p.read_text()) if p.exists() else {"upload_id": upload_id, "files": [], "meta": {}}


def add_file(upload_id: str, name: str, data: bytes) -> str:
    target = folder(upload_id) / safe_name(name)
    n = 2
    while target.exists() and target.read_bytes() != data:
        target = target.with_name(f"{target.stem}-{n}.pdf"); n += 1
    target.write_bytes(data)
    return target.name


def remove_file(upload_id: str, filename: str) -> None:
    target = folder(upload_id) / safe_name(filename)
    if target.exists() and target.parent == folder(upload_id):
        target.unlink()


def set_meta(upload_id: str, item_id: str) -> None:
    m = load(upload_id)
    m.setdefault("meta", {})["item_id"] = item_id.strip() or None
    (folder(upload_id) / "manifest.json").write_text(json.dumps(m, indent=1))


def move_to_item(upload_id: str, item_id: str) -> list[str]:
    """Copy the valid files into data/<item_id>/. Identical files already there are skipped;
    a different file with the same name gets a numbered name rather than overwriting."""
    dest = db.DATA / item_id
    dest.mkdir(parents=True, exist_ok=True)
    moved = []
    for f in load(upload_id)["files"]:
        if f["state"] != "valid":
            continue
        src = folder(upload_id) / f["filename"]
        target = dest / f["filename"]
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest() == f["sha256"]:
                continue
            target = dest / f"{target.stem}-upload-{upload_id[:6]}.pdf"
        shutil.copy2(src, target)
        moved.append(target.name)
    return moved
