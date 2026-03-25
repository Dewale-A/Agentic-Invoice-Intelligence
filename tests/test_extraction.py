"""Tests for extraction and document tools."""

import pytest

from src.models.schemas import DocumentType
from src.tools.document_tools import classify_document
from src.tools.extraction_tools import extract_invoice_fields, _parse_decimal, _parse_date


class TestClassification:
    def test_invoice_classification(self):
        text = "INVOICE #INV-001\nBill To: Company\nAmount Due: $5,000.00\nInvoice Date: 2024-01-01"
        doc_type, confidence = classify_document(text)
        assert doc_type == DocumentType.INVOICE
        assert confidence > 0.5

    def test_receipt_classification(self):
        text = "RECEIPT\nPayment Received\nTransaction ID: TXN-123\nThank you for your payment"
        doc_type, confidence = classify_document(text)
        assert doc_type == DocumentType.RECEIPT

    def test_unknown_classification(self):
        text = "Random text with no keywords"
        doc_type, confidence = classify_document(text)
        assert doc_type == DocumentType.UNKNOWN


class TestExtraction:
    def test_extract_from_structured_text(self):
        text = """
From: Acme Cloud Services
Invoice #: INV-2024-0101
Invoice Date: 03/15/2024
Due Date: 04/14/2024
P.O. Number: PO-2024-001

Cloud Services Q1          1  $13,274.34  $13,274.34

Subtotal: $13,274.34
Tax: $1,725.66
Total Due: $15,000.00
Currency: USD
"""
        invoice = extract_invoice_fields(text, "test.pdf")
        assert invoice.vendor_name == "Acme Cloud Services"
        assert invoice.invoice_number == "INV-2024-0101"
        assert invoice.po_number == "PO-2024-001"
        assert invoice.total is not None
        assert invoice.extraction_confidence > 0.0


class TestParsers:
    def test_parse_decimal(self):
        from decimal import Decimal
        assert _parse_decimal("1,234.56") == Decimal("1234.56")
        assert _parse_decimal(None) is None
        assert _parse_decimal("abc") is None

    def test_parse_date(self):
        d = _parse_date("03/15/2024")
        assert d is not None
        assert d.year == 2024
        assert _parse_date(None) is None
