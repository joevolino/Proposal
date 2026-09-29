"""Turn uploaded supporting documents into text (and raw PDFs) the drafting step can use."""

from __future__ import annotations

import csv
import io
import os
import zipfile
from dataclasses import dataclass, field

import openpyxl
import pdfplumber

from .pricing import parse_pricing_illustration

# Upload categories shown in the UI. Keys are sent as form field names.
CATEGORIES = {
    "medical_rates": "Medical Rates (current / renewal)",
    "aetna_rates": "Aetna Rates (proposed VensureHR medical)",
    "ancillary": "Ancillary Offerings (dental, vision, life, disability, etc.)",
    "pricing_illustration": "VensureHR Pricing Illustration (Admin, WC, Taxes)",
    "roi": "Excel ROI Analysis",
    "transcripts": "Meeting Transcripts & Notes",
    "incumbent": "Incumbent Data (invoices, census, current benefits)",
}

TEXT_EXT = {".txt", ".md", ".vtt", ".srt", ".json", ".log", ".rtf"}
XL_EXT = {".xlsx", ".xlsm", ".xltx", ".xltm"}
IMG_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}

MAX_TEXT_CHARS = 150_000  # per document; larger documents are cut and a warning is returned


@dataclass
class Doc:
    category: str
    name: str
    kind: str  # pdf | text | image
    text: str = ""
    data: bytes = b""
    media_type: str = ""
    pages: int = 0


@dataclass
class Extraction:
    docs: list[Doc] = field(default_factory=list)
    pricing: dict | None = None
    warnings: list[str] = field(default_factory=list)


def extract_files(files: list[tuple[str, str, bytes]]) -> Extraction:
    """files: list of (category, filename, bytes)."""
    out = Extraction()
    for category, name, data in files:
        _extract_one(out, category, name, data, depth=0)
    return out


def _extract_one(out: Extraction, category: str, name: str, data: bytes, depth: int) -> None:
    ext = os.path.splitext(name)[1].lower()
    base = os.path.basename(name)
    if base.startswith("._") or "__MACOSX" in name or not data:
        return
    try:
        if ext == ".zip":
            if depth > 2:
                out.warnings.append(f"Skipped nested archive {name}.")
                return
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for info in sorted(zf.infolist(), key=lambda i: i.filename):
                    if not info.is_dir():
                        _extract_one(out, category, f"{base}/{info.filename}", zf.read(info), depth + 1)
        elif ext == ".pdf":
            out.docs.append(_pdf(category, name, data))
        elif ext in XL_EXT:
            _excel(out, category, name, data)
        elif ext == ".xls":
            out.warnings.append(f"{name}: legacy .xls is not supported; save it as .xlsx and re-upload.")
        elif ext == ".csv":
            text = data.decode("utf-8-sig", errors="replace")
            rows = list(csv.reader(io.StringIO(text)))
            out.docs.append(_text_doc(out, category, name, "\n".join(" | ".join(r) for r in rows)))
        elif ext == ".docx":
            out.docs.append(_text_doc(out, category, name, _docx_text(data)))
        elif ext in IMG_EXT:
            out.docs.append(Doc(category, name, "image", data=data, media_type=IMG_EXT[ext]))
        elif ext in TEXT_EXT or not ext:
            out.docs.append(_text_doc(out, category, name, data.decode("utf-8", errors="replace")))
        else:
            out.warnings.append(f"{name}: unsupported file type {ext}; skipped.")
    except Exception as exc:  # a bad file shouldn't sink the whole proposal
        out.warnings.append(f"{name}: could not be read ({exc}).")


def _text_doc(out: Extraction, category: str, name: str, text: str) -> Doc:
    if len(text) > MAX_TEXT_CHARS:
        out.warnings.append(
            f"{name}: {len(text):,} characters; only the first {MAX_TEXT_CHARS:,} were used. "
            "Split the file or trim it if the rest matters."
        )
        text = text[:MAX_TEXT_CHARS]
    return Doc(category, name, "text", text=text)


def _pdf(category: str, name: str, data: bytes) -> Doc:
    parts = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        pages = len(pdf.pages)
        for i, page in enumerate(pdf.pages, 1):
            parts.append(f"--- page {i} ---\n{page.extract_text() or ''}")
    return Doc(category, name, "pdf", text="\n".join(parts), data=data, media_type="application/pdf", pages=pages)


def _excel(out: Extraction, category: str, name: str, data: bytes) -> None:
    import tempfile

    suffix = os.path.splitext(name)[1].lower()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        path = tmp.name
    try:
        pricing = parse_pricing_illustration(path)
        if pricing is not None:
            if out.pricing is None:
                out.pricing = pricing
                out.pricing["file"] = name
            else:
                out.warnings.append(f"{name}: more than one pricing illustration uploaded; using {out.pricing['file']}.")
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
        lines = []
        for ws in wb.worksheets:
            if getattr(ws, "sheet_state", "visible") != "visible":
                continue
            lines.append(f"=== Sheet: {ws.title} ===")
            for row in ws.iter_rows(values_only=True):
                cells = [_cell(v) for v in row]
                while cells and cells[-1] == "":
                    cells.pop()
                if any(cells):
                    lines.append(" | ".join(cells))
        out.docs.append(_text_doc(out, category, name, "\n".join(lines)))
    finally:
        os.unlink(path)


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.6g}" if abs(v) < 1 else f"{v:,.2f}".rstrip("0").rstrip(".")
    s = str(v).strip()
    return "" if s.startswith("#N/A") else s.replace("\n", " ")


def _docx_text(data: bytes) -> str:
    import docx

    d = docx.Document(io.BytesIO(data))
    lines = [p.text for p in d.paragraphs if p.text.strip()]
    for table in d.tables:
        for row in table.rows:
            lines.append(" | ".join(c.text.strip() for c in row.cells))
    return "\n".join(lines)
