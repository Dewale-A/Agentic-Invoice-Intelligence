"""Shared pytest fixtures for AgenticInvoiceIntelligence tests."""

from __future__ import annotations

import tempfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from src.data.database import DB_PATH, bootstrap, init_db, seed_db
from src.models.schemas import (
    DocumentType,
    ExtractedInvoice,
    InvoiceLineItem,
    InvoiceStatus,
)


@pytest.fixture(autouse=True)
def _fresh_db(tmp_path, monkeypatch):
    """Use a fresh temp database for every test."""
    db_file = tmp_path / "test.db"
    monkeypatch.setattr("src.data.database.DB_PATH", db_file)
    # Also patch any module that imports DB_PATH
    for mod in [
        "src.governance.engine",
        "src.governance.audit",
        "src.tools.validation_tools",
        "src.tools.anomaly_tools",
    ]:
        try:
            import importlib
            m = importlib.import_module(mod)
        except ImportError:
            continue
    init_db(db_file)
    seed_db(db_file)
    yield db_file


@pytest.fixture
def sample_invoice() -> ExtractedInvoice:
    return ExtractedInvoice(
        source_filename="test_invoice.pdf",
        document_type=DocumentType.INVOICE,
        vendor_name="Acme Cloud Services",
        invoice_number="INV-TEST-001",
        invoice_date=date.today(),
        po_number="PO-2024-001",
        currency="USD",
        line_items=[
            InvoiceLineItem(
                description="Cloud Services Q1",
                quantity=Decimal("1"),
                unit_price=Decimal("13274.34"),
                total=Decimal("13274.34"),
            )
        ],
        subtotal=Decimal("13274.34"),
        tax=Decimal("1725.66"),
        total=Decimal("15000.00"),
        extraction_confidence=0.95,
        ocr_confidence=1.0,
        status=InvoiceStatus.PROCESSING,
    )


@pytest.fixture
def high_value_invoice() -> ExtractedInvoice:
    return ExtractedInvoice(
        source_filename="high_value.pdf",
        document_type=DocumentType.INVOICE,
        vendor_name="NexGen Software",
        invoice_number="NXG-TEST-001",
        invoice_date=date.today(),
        po_number="PO-2024-013",
        currency="USD",
        total=Decimal("100000.00"),
        extraction_confidence=0.90,
        ocr_confidence=1.0,
        status=InvoiceStatus.PROCESSING,
    )


@pytest.fixture
def unknown_vendor_invoice() -> ExtractedInvoice:
    return ExtractedInvoice(
        source_filename="unknown_vendor.pdf",
        document_type=DocumentType.INVOICE,
        vendor_name="ShadowTech Solutions Inc.",
        invoice_number="ST-001",
        invoice_date=date.today(),
        total=Decimal("9000.00"),
        extraction_confidence=0.85,
        ocr_confidence=1.0,
        status=InvoiceStatus.PROCESSING,
    )
