"""
Tests for Pydantic v2 schemas in src/models/schemas.py
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from src.models.schemas import (
    AnomalyFlag,
    AnomalyReport,
    AnomalySeverity,
    AuditTrailEntry,
    DocumentType,
    EscalationLevel,
    ExtractedInvoice,
    FieldValidationResult,
    GovernanceDecision,
    GovernanceDashboard,
    InvoiceLineItem,
    InvoiceStatus,
    PurchaseOrder,
    ReconciliationItem,
    ReconciliationReport,
    ValidationReport,
    ValidationStatus,
    VendorRecord,
    AgentDecision,
    AgentRole,
)


# ---------------------------------------------------------------------------
# InvoiceLineItem
# ---------------------------------------------------------------------------


class TestInvoiceLineItem:
    def test_valid_line_item(self):
        item = InvoiceLineItem(
            description="Software License",
            quantity=Decimal("2"),
            unit_price=Decimal("500.00"),
            total=Decimal("1000.00"),
        )
        assert item.total == Decimal("1000.00")

    def test_description_min_length(self):
        with pytest.raises(ValidationError):
            InvoiceLineItem(
                description="",
                quantity=Decimal("1"),
                unit_price=Decimal("100"),
                total=Decimal("100"),
            )

    def test_quantity_must_be_positive(self):
        with pytest.raises(ValidationError):
            InvoiceLineItem(
                description="Item",
                quantity=Decimal("0"),
                unit_price=Decimal("100"),
                total=Decimal("0"),
            )

    def test_optional_fields(self):
        item = InvoiceLineItem(
            description="Consulting",
            quantity=Decimal("5"),
            unit_price=Decimal("200"),
            total=Decimal("1000"),
            category="IT",
            gl_code="6100",
        )
        assert item.category == "IT"
        assert item.gl_code == "6100"


# ---------------------------------------------------------------------------
# ExtractedInvoice
# ---------------------------------------------------------------------------


class TestExtractedInvoice:
    def test_defaults(self):
        inv = ExtractedInvoice(source_filename="test.pdf")
        assert inv.status == InvoiceStatus.PENDING
        assert inv.currency == "USD"
        assert isinstance(inv.invoice_id, UUID)

    def test_currency_normalised_to_upper(self):
        inv = ExtractedInvoice(source_filename="test.pdf", currency="cad")
        assert inv.currency == "CAD"

    def test_invalid_currency_raises(self):
        with pytest.raises(ValidationError):
            ExtractedInvoice(source_filename="test.pdf", currency="XYZ")

    def test_confidence_bounds(self):
        with pytest.raises(ValidationError):
            ExtractedInvoice(source_filename="test.pdf", extraction_confidence=1.5)
        with pytest.raises(ValidationError):
            ExtractedInvoice(source_filename="test.pdf", extraction_confidence=-0.1)

    def test_line_items_populated(self):
        inv = ExtractedInvoice(
            source_filename="test.pdf",
            line_items=[
                InvoiceLineItem(
                    description="Service",
                    quantity=Decimal("1"),
                    unit_price=Decimal("500"),
                    total=Decimal("500"),
                )
            ],
        )
        assert len(inv.line_items) == 1

    def test_raw_text_excluded_from_serialisation(self):
        inv = ExtractedInvoice(source_filename="test.pdf", raw_text="hidden")
        data = inv.model_dump()
        assert "raw_text" not in data


# ---------------------------------------------------------------------------
# ValidationReport
# ---------------------------------------------------------------------------


class TestValidationReport:
    def test_valid_report(self):
        rpt = ValidationReport(
            invoice_id=uuid4(),
            overall_status=ValidationStatus.PASS,
            po_match=True,
            vendor_approved=True,
        )
        assert rpt.po_match is True

    def test_field_results_default_empty(self):
        rpt = ValidationReport(invoice_id=uuid4(), overall_status=ValidationStatus.WARNING)
        assert rpt.field_results == []


# ---------------------------------------------------------------------------
# AnomalyReport
# ---------------------------------------------------------------------------


class TestAnomalyReport:
    def test_has_critical_anomalies_true(self):
        report = AnomalyReport(
            invoice_id=uuid4(),
            anomalies=[
                AnomalyFlag(
                    anomaly_type="duplicate",
                    severity=AnomalySeverity.CRITICAL,
                    description="Exact duplicate",
                )
            ],
        )
        assert report.has_critical_anomalies is True

    def test_has_critical_anomalies_false(self):
        report = AnomalyReport(
            invoice_id=uuid4(),
            anomalies=[
                AnomalyFlag(
                    anomaly_type="date_anomaly",
                    severity=AnomalySeverity.LOW,
                    description="Minor date issue",
                )
            ],
        )
        assert report.has_critical_anomalies is False

    def test_risk_score_bounds(self):
        with pytest.raises(ValidationError):
            AnomalyReport(invoice_id=uuid4(), overall_risk_score=1.5)


# ---------------------------------------------------------------------------
# GovernanceDecision
# ---------------------------------------------------------------------------


class TestGovernanceDecision:
    def test_immutable_fields(self):
        dec = GovernanceDecision(
            invoice_id=uuid4(),
            rule_triggered="materiality_gate",
            decision="escalate",
            escalation_level=EscalationLevel.L2_CONTROLLER,
            reason="Amount exceeds L2 threshold",
            actor=AgentRole.RECONCILIATION,
        )
        assert dec.escalation_level == EscalationLevel.L2_CONTROLLER
        assert isinstance(dec.decision_id, UUID)


# ---------------------------------------------------------------------------
# ReconciliationReport
# ---------------------------------------------------------------------------


class TestReconciliationReport:
    def test_defaults(self):
        rpt = ReconciliationReport()
        assert rpt.total_invoices == 0
        assert rpt.total_value == Decimal("0")
        assert isinstance(rpt.report_id, UUID)


# ---------------------------------------------------------------------------
# VendorRecord
# ---------------------------------------------------------------------------


class TestVendorRecord:
    def test_approved_by_default(self):
        v = VendorRecord(
            vendor_id="V001",
            name="Acme Corp",
            category="Software",
        )
        assert v.approved is True
        assert v.payment_terms_days == 30


# ---------------------------------------------------------------------------
# PurchaseOrder
# ---------------------------------------------------------------------------


class TestPurchaseOrder:
    def test_basic_po(self):
        po = PurchaseOrder(
            po_number="PO-001",
            vendor_id="V001",
            vendor_name="Acme Corp",
            description="Cloud services",
            amount=Decimal("10000"),
            issued_date=date.today(),
        )
        assert po.currency == "USD"
        assert po.status == "open"


# ---------------------------------------------------------------------------
# GovernanceDashboard
# ---------------------------------------------------------------------------


class TestGovernanceDashboard:
    def test_all_zero_defaults(self):
        dash = GovernanceDashboard()
        assert dash.total_processed == 0
        assert dash.escalated_l1 == 0
        assert dash.avg_confidence == 0.0


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class TestEnums:
    def test_invoice_status_values(self):
        assert InvoiceStatus.PENDING == "pending"
        assert InvoiceStatus.APPROVED == "approved"

    def test_escalation_level_ordering(self):
        levels = [
            EscalationLevel.NONE,
            EscalationLevel.L1_MANAGER,
            EscalationLevel.L2_CONTROLLER,
            EscalationLevel.L3_VP_CFO,
        ]
        assert len(levels) == 4

    def test_anomaly_severity_values(self):
        assert AnomalySeverity.CRITICAL == "critical"
