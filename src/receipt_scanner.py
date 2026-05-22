from __future__ import annotations

import re
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Optional

from pypdf import PdfReader

try:
    import pytesseract
    from PIL import Image

    HAS_OCR = True
except ImportError:
    HAS_OCR = False


AMOUNT_RE = re.compile(r"\$?\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})|\d+\.\d{2})")
DATE_RE = re.compile(
    r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})\b",
    re.IGNORECASE,
)

CATEGORY_KEYWORDS = {
    "meals": ["restaurant", "cafe", "coffee", "dining", "grill", "pizza", "starbucks", "lunch", "dinner"],
    "rideshare": ["uber", "lyft", "taxi", "cab"],
    "hotels": ["hotel", "inn", "marriott", "hilton", "lodging"],
    "flights": ["airline", "airways", "delta", "united", "flight"],
    "software": ["software", "saas", "subscription", "adobe", "microsoft"],
    "alcohol": ["bar", "brewery", "wine", "liquor"],
    "gifts": ["gift", "flowers", "basket"],
}


def extract_text_from_file(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".pdf":
        reader = PdfReader(str(path))
        chunks = [page.extract_text() or "" for page in reader.pages]
        text = "\n".join(chunks).strip()
        if text:
            return text
        if HAS_OCR:
            return _ocr_pdf_pages(path)
        return ""

    if ext in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff"}:
        if HAS_OCR:
            return pytesseract.image_to_string(Image.open(path))
        return ""

    return path.read_text(encoding="utf-8", errors="ignore")


def _ocr_pdf_pages(path: Path) -> str:
    try:
        from pdf2image import convert_from_path

        images = convert_from_path(str(path), first_page=1, last_page=1)
        if images:
            return pytesseract.image_to_string(images[0])
    except Exception:
        pass
    return ""


def _guess_category(text: str) -> str:
    lower = text.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(k in lower for k in keywords):
            return category.title() if category != "rideshare" else "Rideshare"
    return "Meals"


def _parse_amount(text: str) -> Optional[float]:
    amounts = []
    for match in AMOUNT_RE.finditer(text):
        raw = match.group(1).replace(",", "")
        try:
            val = float(raw)
            if val > 0:
                amounts.append(val)
        except ValueError:
            continue
    return max(amounts) if amounts else None


def _parse_date(text: str) -> str:
    match = DATE_RE.search(text)
    if match:
        return match.group(1)
    return date.today().isoformat()


def _parse_vendor(text: str) -> str:
    for line in text.splitlines():
        cleaned = line.strip()
        if len(cleaned) >= 3 and not AMOUNT_RE.fullmatch(cleaned.replace("$", "")):
            return cleaned[:80]
    return "Scanned Receipt"


def parse_receipt_text(text: str, filename: str = "") -> dict:
    combined = f"{filename}\n{text}"
    amount = _parse_amount(combined) or 0.0
    expense_date = _parse_date(combined)
    vendor = _parse_vendor(text)
    category = _guess_category(combined)
    today = date.today().isoformat()

    return {
        "employee_id": "E-SCAN",
        "category": category,
        "amount": round(amount, 2),
        "currency": "USD",
        "expense_date": expense_date,
        "submission_date": today,
        "receipt_provided": "yes",
        "manager_approval": "no",
        "pre_approval": "no",
        "flight_class": "",
        "notes": f"Scanned from receipt: {vendor}",
        "vendor": vendor,
        "raw_text": text[:2000],
    }


def scan_receipt_file(path: Path, employee_id: str = "") -> dict:
    """Run Receipt Analysis Agent (LLM if configured, else OCR rules)."""
    from .agents import ReceiptAnalysisAgent

    return ReceiptAnalysisAgent().run(path, employee_id=employee_id)
