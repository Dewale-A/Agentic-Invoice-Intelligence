"""
Tests for the GovernanceEngine in src/governance/engine.py
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest

from src.governance.engine import (
    AGENT_CONFIDENCE_THRESHOLD,
    MATERIALITY_L1,
    MATERIALITY_L2,
    MATERIALITY_L3,
    OCR_CONFIDENCE_THRESHOLD,
    GovernanceEngine,
    evaluate_agent_confidence,
    evaluate_materiality,
    evaluate_ocr_confidence,
    evaluate_unknown_vendor,
)
from src.models.schemas import (
    AgentRole,
    AnomalyReport,
    EscalationLevel,
    ExtractedInvoice,
    InvoiceStatus,
    ValidationReport,
    ValidationStatus,
)


# ---------------------------------------------------------------------------
# OCR confidence gate
# ---------------------------------------------------------------------------


class TestOcrConfidenceGate:
    def test_below_threshold_triggers_decision(self, sample_invoice):
        sample_invoice.ocr_used = True
        sample_invoice.ocr_confidence = 0.60
        with patch("src.governance.engine._persist"):
            decision = evaluate_ocr_confidence(sample_invoice)
        assert decision is not None
        assert decision.decision == "escalate"
        assert decision.escalation_level == EscalationLevel.HUMAN_REVIEW
        assert decision.rule_triggered == "ocr_confidence_gate"

    def test_above_threshold_no_decision(self, sample_invoice):
        sample_invoice.ocr_used = True
        sample_invoice.ocr_confidence = 0.95
        with patch("src.governance.engine._persist"):
            decision = evaluate_ocr_confidence(sample_invoice)
        assert decision is None

    def test_no_ocr_skips_gate(self, sample_invoice):
        sample_invoice.ocr_used = False
        sample_invoice.ocr_confidence = 0.50
        with patch("src.governance.engine._persist"):
            decision = evaluate_ocr_confidence(sample_invoice)
        assert decision is None


# ---------------------------------------------------------------------------
# Unknown vendor gate
# ---------------------------------------------------------------------------


class TestUnknownVendorGate:
    def test_known_vendor_passes(self, sample_invoice):
        with patch("src.governance.engine.is_approved_vendor", return_value=True), \
             patch("src.governance.engine._persist"):
            decision = evaluate_unknown_vendor(sample_invoice)
        assert decision is None

    def test_unknown_vendor_escalates(self, unknown_vendor_invoice):
        with patch("src.governance.engine.is_approved_vendor", return_value=False), \
             patch("src.governance.engine._persist"):
            decision = evaluate_unknown_vendor(unknown_vendor_invoice)
        assert decision is not None
        assert decision.decision == "escalate"
        assert decision.rule_triggered == "unknown_vendor"

    def test_missing_vendor_name_escalates(self, sample_invoice):
        sample_invoice.vendor_name = None
        with patch("src.governance.engine._persist"):
            decision = evaluate_unknown_vendor(sample_invoice)
        assert decision is not None
        assert decision.escalation_level == EscalationLevel.HUMAN_REVIEW


# ---------------------------------------------------------------------------
# Materiality gate
# ---------------------------------------------------------------------------


class TestMaterialityGate:
    def test_below_l1_no_decision(self, sample_invoice):
        sample_invoice.total = Decimal("1000.00")
        with patch("src.governance.engine._persist"):
            decision = evaluate_materiality(sample_invoice)
        assert decision is None

    def test_l1_escalation(self, sample_invoice):
        sample_invoice.total = Decimal("6000.00")
        with patch("src.governance.engine._persist"):
            decision = evaluate_materiality(sample_invoice)
        assert decision is not None
        assert decision.escalation_level == EscalationLevel.L1_MANAGER

    def test_l2_escalation(self, sample_invoice):
        sample_invoice.total = Decimal("30000.00")
        with patch("src.governance.engine._persist"):
            decision = evaluate_materiality(sample_invoice)
        assert decision.escalation_level == EscalationLevel.L2_CONTROLLER

    def test_l3_escalation(self, high_value_invoice):
        high_value_invoice.total = Decimal("150000.00")
        with patch("src.governance.engine._persist"):
            decision = evaluate_materiality(high_value_invoice)
        assert decision.escalation_level == EscalationLevel.L3_VP_CFO

    def test_no_total_skips_gate(self, sample_invoice):
        sample_invoice.total = None
        with patch("src.governance.engine._persist"):
            decision = evaluate_materiality(sample_invoice)
        assert decision is None


# ---------------------------------------------------------------------------
# Agent confidence gate
# ---------------------------------------------------------------------------


class TestAgentConfidenceGate:
    def test_low_confidence_escalates(self, sample_invoice):
        with patch("src.governance.engine._persist"):
            decision = evaluate_agent_confidence(
                sample_invoice, 0.50, AgentRole.DATA_EXTRACTION
            )
        assert decision is not None
        assert decision.rule_triggered == "agent_confidence_gate"
        assert decision.actual_value == 0.50

    def test_high_confidence_passes(self, sample_invoice):
        with patch("src.governance.engine._persist"):
            decision = evaluate_agent_confidence(
                sample_invoice, 0.95, AgentRole.VALIDATION
            )
        assert decision is None

    def test_exactly_at_threshold_passes(self, sample_invoice):
        with patch("src.governance.engine._persist"):
            decision = evaluate_agent_confidence(
                sample_invoice, AGENT_CONFIDENCE_THRESHOLD, AgentRole.VALIDATION
            )
        assert decision is None


# ---------------------------------------------------------------------------
# GovernanceEngine orchestrator
# ---------------------------------------------------------------------------


class TestGovernanceEngine:
    def test_evaluate_post_intake_clean(self, sample_invoice):
        engine = GovernanceEngine()
        sample_invoice.ocr_used = False
        with patch("src.governance.engine._persist"):
            decisions = engine.evaluate_post_intake(sample_invoice)
        assert decisions == []

    def test_evaluate_post_extraction_low_confidence(self, sample_invoice):
        engine = GovernanceEngine()
        with patch("src.governance.engine.check_duplicate_invoice", return_value=None), \
             patch("src.governance.engine._persist"):
            decisions = engine.evaluate_post_extraction(sample_invoice, 0.40)
        assert any(d.rule_triggered == "agent_confidence_gate" for d in decisions)

    def test_determine_final_status_no_decisions(self):
        engine = GovernanceEngine()
        status = engine.determine_final_status([])
        assert status == InvoiceStatus.VALIDATED

    def test_determine_final_status_block(self, sample_invoice):
        engine = GovernanceEngine()
        from src.models.schemas import GovernanceDecision
        block_decision = GovernanceDecision(
            invoice_id=sample_invoice.invoice_id,
            rule_triggered="duplicate_detection",
            decision="block",
            reason="Duplicate",
            actor=AgentRole.ANOMALY_DETECTION,
        )
        status = engine.determine_final_status([block_decision])
        assert status == InvoiceStatus.REJECTED

    def test_determine_final_status_escalate(self, sample_invoice):
        engine = GovernanceEngine()
        from src.models.schemas import GovernanceDecision
        esc_decision = GovernanceDecision(
            invoice_id=sample_invoice.invoice_id,
            rule_triggered="materiality_gate",
            decision="escalate",
            reason="High value",
            actor=AgentRole.RECONCILIATION,
        )
        status = engine.determine_final_status([esc_decision])
        assert status == InvoiceStatus.ON_HOLD

    def test_evaluate_post_validation(self, sample_invoice):
        engine = GovernanceEngine()
        vr = ValidationReport(
            invoice_id=sample_invoice.invoice_id,
            overall_status=ValidationStatus.PASS,
            validation_confidence=0.95,
            vendor_approved=True,
        )
        with patch("src.governance.engine.is_approved_vendor", return_value=True), \
             patch("src.governance.engine.get_purchase_order", return_value=None), \
             patch("src.governance.engine._persist"):
            decisions = engine.evaluate_post_validation(sample_invoice, vr)
        assert isinstance(decisions, list)
