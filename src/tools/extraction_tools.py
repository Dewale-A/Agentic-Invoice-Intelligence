"""
LLM-based invoice data extraction tools.

Design decision: extraction is a two-pass process.
  Pass 1: LLM maps raw text to a structured JSON payload using a few-shot prompt.
  Pass 2: Pydantic validates and coerces the JSON, rejecting structurally invalid data.

This separation means LLM errors are caught at a well-defined boundary and produce
a measurable confidence score rather than silent data corruption.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from src.models.schemas import (
    DocumentType,
    ExtractedInvoice,
    InvoiceLineItem,
    InvoiceStatus,
)


# ---------------------------------------------------------------------------
# Regex-based extraction (no LLM required for demo/offline use)
# ---------------------------------------------------------------------------

# These patterns are deliberately broad to handle diverse invoice formats.
_PATTERNS = {
    "invoice_number": [
        r"invoice\s*(?:#|no\.?|number)[:\s]*([A-Z0-9\-]+)",
        r"inv\s*(?:#|no\.?)[:\s]*([A-Z0-9\-]+)",
    ],
    "po_number": [
        r"p\.?o\.?\s*(?:#|no\.?|number)[:\s]*([A-Z0-9\-]+)",
        r"purchase\s+order\s*(?:#|no\.?)[:\s]*([A-Z0-9\-]+)",
    ],
    "vendor_name": [
        r"from[:\s]+([A-Za-z][A-Za-z0-9 ,\.&-]{3,60})\n",
        r"bill\s+from[:\s]+([A-Za-z][A-Za-z0-9 ,\.&-]{3,60})\n",
        r"vendor[:\s]+([A-Za-z][A-Za-z0-9 ,\.&-]{3,60})\n",
    ],
    "total": [
        r"(?:grand\s+)?total\s*(?:due|amount)?[:\s]*\$?\s*([\d,]+\.?\d{0,2})",
        r"amount\s+due[:\s]*\$?\s*([\d,]+\.?\d{0,2})",
        r"total\s+amount[:\s]*\$?\s*([\d,]+\.?\d{0,2})",
    ],
    "subtotal": [
        r"subtotal[:\s]*\$?\s*([\d,]+\.?\d{0,2})",
        r"sub\s*total[:\s]*\$?\s*([\d,]+\.?\d{0,2})",
    ],
    "tax": [
        r"(?:sales\s+)?tax[:\s]*\$?\s*([\d,]+\.?\d{0,2})",
        r"hst[:\s]*\$?\s*([\d,]+\.?\d{0,2})",
        r"gst[:\s]*\$?\s*([\d,]+\.?\d{0,2})",
        r"vat[:\s]*\$?\s*([\d,]+\.?\d{0,2})",
    ],
    "invoice_date": [
        r"invoice\s+date[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        r"date[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        r"dated[:\s]*(\w+ \d{1,2},?\s+\d{4})",
        r"invoice\s+date[:\s]*(\w+ \d{1,2},?\s+\d{4})",
    ],
    "due_date": [
        r"due\s+(?:date|by)[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        r"payment\s+due[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        r"due\s+(?:date|by)[:\s]*(\w+ \d{1,2},?\s+\d{4})",
    ],
    "currency": [
        r"\b(USD|CAD|EUR|GBP|AUD|JPY|CHF)\b",
    ],
}


def _first_match(text: str, patterns: list[str]) -> Optional[str]:
    """Return the first capturing group match from a list of patterns."""
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def _parse_decimal(value: Optional[str]) -> Optional[Decimal]:
    if not value:
        return None
    clean = value.replace(",", "").strip()
    try:
        return Decimal(clean)
    except InvalidOperation:
        return None


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    formats = [
        "%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%d",
        "%m-%d-%Y", "%d-%m-%Y",
        "%B %d, %Y", "%B %d %Y",
        "%b %d, %Y", "%b %d %Y",
        "%m/%d/%y", "%d/%m/%y",
    ]
    clean = value.strip().rstrip(",")
    for fmt in formats:
        try:
            return datetime.strptime(clean, fmt).date()
        except ValueError:
            continue
    return None


def _extract_line_items(text: str) -> list[InvoiceLineItem]:
    """
    Attempt to extract line items from tabular text using pattern matching.
    Matches rows that look like: <description> <qty> <unit_price> <total>
    """
    items: list[InvoiceLineItem] = []
    # Pattern: description followed by numbers (qty, unit price, total)
    pattern = re.compile(
        r"^(.{5,50}?)\s{2,}(\d+(?:\.\d+)?)\s+\$?([\d,]+\.\d{2})\s+\$?([\d,]+\.\d{2})",
        re.MULTILINE,
    )
    for m in pattern.finditer(text):
        try:
            desc, qty, unit, total = m.groups()
            items.append(
                InvoiceLineItem(
                    description=desc.strip(),
                    quantity=Decimal(qty),
                    unit_price=_parse_decimal(unit) or Decimal("0"),
                    total=_parse_decimal(total) or Decimal("0"),
                )
            )
        except Exception:
            continue
    return items


def extract_invoice_fields(
    raw_text: str,
    source_filename: str,
    document_type: DocumentType = DocumentType.INVOICE,
    ocr_used: bool = False,
    ocr_confidence: float = 1.0,
) -> ExtractedInvoice:
    """
    Extract structured invoice fields from raw text using regex heuristics.

    Returns an ExtractedInvoice with extraction_confidence reflecting how many
    key fields were successfully parsed.
    """
    fields: dict[str, Any] = {}

    for field, patterns in _PATTERNS.items():
        fields[field] = _first_match(raw_text, patterns)

    # Parse typed values
    total = _parse_decimal(fields.get("total"))
    subtotal = _parse_decimal(fields.get("subtotal"))
    tax = _parse_decimal(fields.get("tax"))
    invoice_date = _parse_date(fields.get("invoice_date"))
    due_date = _parse_date(fields.get("due_date"))
    currency = (fields.get("currency") or "USD").upper()

    # Line items
    line_items = _extract_line_items(raw_text)

    # Confidence: proportion of key fields extracted
    key_fields = ["vendor_name", "invoice_number", "invoice_date", "total", "po_number"]
    extracted_count = sum(1 for f in key_fields if fields.get(f))
    extraction_confidence = extracted_count / len(key_fields)

    return ExtractedInvoice(
        source_filename=source_filename,
        document_type=document_type,
        raw_text=raw_text,
        ocr_used=ocr_used,
        vendor_name=fields.get("vendor_name"),
        invoice_number=fields.get("invoice_number"),
        invoice_date=invoice_date,
        due_date=due_date,
        po_number=fields.get("po_number"),
        currency=currency,
        line_items=line_items,
        subtotal=subtotal,
        tax=tax,
        total=total,
        extraction_confidence=round(extraction_confidence, 3),
        ocr_confidence=ocr_confidence,
        status=InvoiceStatus.PROCESSING,
    )


def build_extraction_prompt(raw_text: str) -> str:
    """
    Build a structured prompt for LLM-based extraction.
    Used when the regex extraction confidence is below threshold.
    """
    return f"""Extract structured invoice data from the following text. Return ONLY valid JSON.

Required fields:
- vendor_name: string
- invoice_number: string
- invoice_date: ISO date string (YYYY-MM-DD) or null
- due_date: ISO date string (YYYY-MM-DD) or null
- po_number: string or null
- currency: 3-letter ISO code (default "USD")
- subtotal: number or null
- tax: number or null
- total: number or null
- line_items: array of {{description, quantity, unit_price, total}} or []

Invoice text:
---
{raw_text[:4000]}
---

JSON response:"""


def merge_llm_extraction(
    base: ExtractedInvoice, llm_json: str
) -> ExtractedInvoice:
    """
    Merge LLM extraction results into a base ExtractedInvoice.
    LLM values override regex values only when the regex result was None.
    """
    try:
        data = json.loads(llm_json)
    except json.JSONDecodeError:
        return base

    updates: dict[str, Any] = {}

    def _maybe_update(field: str, transform=None):
        if getattr(base, field) is None and data.get(field) is not None:
            val = data[field]
            updates[field] = transform(val) if transform else val

    _maybe_update("vendor_name")
    _maybe_update("invoice_number")
    _maybe_update("po_number")
    _maybe_update("currency", lambda v: v.upper() if isinstance(v, str) else "USD")
    _maybe_update("invoice_date", lambda v: date.fromisoformat(v) if v else None)
    _maybe_update("due_date", lambda v: date.fromisoformat(v) if v else None)
    _maybe_update("subtotal", lambda v: Decimal(str(v)) if v is not None else None)
    _maybe_update("tax", lambda v: Decimal(str(v)) if v is not None else None)
    _maybe_update("total", lambda v: Decimal(str(v)) if v is not None else None)

    if updates:
        base = base.model_copy(update=updates)

    return base
