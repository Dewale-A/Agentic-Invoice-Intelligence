"""
Document intake tools: PDF parsing, OCR fallback, and document classification.

Design decision: pdfplumber is the primary extraction engine because it preserves
layout and handles multi-column invoices well. pytesseract OCR is a fallback for
scanned or image-only PDFs. Classification uses keyword heuristics with confidence
scoring rather than a separate ML model, keeping inference fast and offline.
"""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Optional

# pdfplumber and pytesseract are optional at import time so the module loads
# even in test environments without the full ML stack.
try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False

try:
    import pytesseract
    from PIL import Image
    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False

from src.models.schemas import DocumentType


# ---------------------------------------------------------------------------
# Document classification
# ---------------------------------------------------------------------------

# Keyword weight map for document classification
_CLASSIFICATION_KEYWORDS: dict[DocumentType, list[str]] = {
    DocumentType.INVOICE: [
        "invoice", "invoice #", "invoice number", "bill to", "amount due",
        "invoice date", "remit to", "net 30", "payment terms",
    ],
    DocumentType.RECEIPT: [
        "receipt", "payment received", "paid", "thank you for your payment",
        "transaction id", "receipt number",
    ],
    DocumentType.PURCHASE_ORDER: [
        "purchase order", "po number", "po #", "ship to", "requisition",
        "order confirmation", "ordered by",
    ],
    DocumentType.STATEMENT: [
        "statement", "account statement", "balance forward", "statement date",
        "outstanding balance", "previous balance",
    ],
}


def classify_document(text: str) -> tuple[DocumentType, float]:
    """
    Classify a document based on keyword frequency scoring.

    Returns (DocumentType, confidence) where confidence is in [0, 1].
    """
    lower = text.lower()
    scores: dict[DocumentType, float] = {}

    for doc_type, keywords in _CLASSIFICATION_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in lower)
        scores[doc_type] = hits / len(keywords)

    if not any(scores.values()):
        return DocumentType.UNKNOWN, 0.0

    best_type = max(scores, key=lambda k: scores[k])
    best_score = scores[best_type]

    # Normalize confidence: full keyword match = 1.0, partial is proportional
    confidence = min(best_score * 2.5, 1.0)  # scale up so 40% keyword hit = ~1.0
    return best_type, round(confidence, 3)


# ---------------------------------------------------------------------------
# PDF text extraction
# ---------------------------------------------------------------------------


def extract_text_from_pdf(file_path: Path) -> tuple[str, float, bool]:
    """
    Extract text from a PDF file.

    Attempts pdfplumber first. If no text is found (scanned PDF), falls back
    to pytesseract OCR on rendered page images.

    Returns:
        (text, ocr_confidence, ocr_used)
        - text:           extracted plain text
        - ocr_confidence: 1.0 for digital PDFs; tesseract mean confidence for OCR
        - ocr_used:       True if OCR fallback was triggered
    """
    if not file_path.exists():
        raise FileNotFoundError(f"PDF not found: {file_path}")

    # --- Attempt pdfplumber ---
    if HAS_PDFPLUMBER:
        text, ocr_conf, ocr_used = _extract_with_pdfplumber(file_path)
        if text.strip():
            return text, ocr_conf, ocr_used

    # --- OCR fallback ---
    if HAS_TESSERACT:
        return _extract_with_ocr(file_path)

    raise RuntimeError(
        "No extraction engine available. Install pdfplumber and/or pytesseract."
    )


def _extract_with_pdfplumber(file_path: Path) -> tuple[str, float, bool]:
    """Extract text using pdfplumber. Returns empty string if PDF has no text layer."""
    pages_text: list[str] = []
    with pdfplumber.open(str(file_path)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            pages_text.append(page_text)

    full_text = "\n\n".join(pages_text)
    return full_text, 1.0, False


def _extract_with_ocr(file_path: Path) -> tuple[str, float, bool]:
    """Extract text using Tesseract OCR from rendered PDF pages."""
    if not HAS_TESSERACT or not HAS_PDFPLUMBER:
        raise RuntimeError("pytesseract and Pillow are required for OCR fallback.")

    pages_text: list[str] = []
    confidence_scores: list[float] = []

    with pdfplumber.open(str(file_path)) as pdf:
        for page in pdf.pages:
            # Render at 200 DPI for reasonable OCR quality
            img = page.to_image(resolution=200).original
            ocr_data = pytesseract.image_to_data(
                img, output_type=pytesseract.Output.DICT
            )
            words = [w for w in ocr_data["text"] if w.strip()]
            confs = [
                c / 100.0
                for c, w in zip(ocr_data["conf"], ocr_data["text"])
                if w.strip() and c >= 0
            ]
            pages_text.append(" ".join(words))
            if confs:
                confidence_scores.append(sum(confs) / len(confs))

    full_text = "\n\n".join(pages_text)
    avg_confidence = (
        sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0.0
    )
    return full_text, round(avg_confidence, 3), True


# ---------------------------------------------------------------------------
# Convenience wrapper
# ---------------------------------------------------------------------------


def process_document(file_path: Path) -> dict:
    """
    Full document intake: extract text, classify type, and return structured result.

    Returns a dict suitable for passing to the Data Extraction agent.
    """
    text, ocr_confidence, ocr_used = extract_text_from_pdf(file_path)
    doc_type, classification_confidence = classify_document(text)

    return {
        "filename": file_path.name,
        "raw_text": text,
        "document_type": doc_type,
        "ocr_used": ocr_used,
        "ocr_confidence": ocr_confidence,
        "classification_confidence": classification_confidence,
        "page_count": _count_pages(file_path),
        "char_count": len(text),
    }


def _count_pages(file_path: Path) -> int:
    if HAS_PDFPLUMBER:
        try:
            with pdfplumber.open(str(file_path)) as pdf:
                return len(pdf.pages)
        except Exception:
            pass
    return 0
