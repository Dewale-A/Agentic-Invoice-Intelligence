"""
Governance Engine for AgenticInvoiceIntelligence.

Design decision: governance is applied INLINE between each agent stage rather
than as a post-processing step. This ensures that a high-risk invoice cannot
progress through the pipeline undetected. Rules are evaluated in priority order:
1. OCR confidence gate  (blocks low-quality extractions early)
2. Duplicate detection  (blocks re-processing before any downstream work)
3. Unknown vendor hold  (prevents payment to unverified parties)
4. Amount variance      (flags discrepancies against PO)
5. Materiality gates    (routes to appropriate approval level)
6. Agent confidence     (catches low-confidence agent outputs)

All decisions are persisted to the immutable audit trail.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import uuid4

from src.data.database import (
    append_audit_entry,
    check_duplicate_invoice,
    get_purchase_order,
    is_approved_vendor,
    save_governance_decision,
)
from src.models.schemas import (
    AgentRole,
    AnomalyReport,
    EscalationLevel,
    ExtractedInvoice,
    GovernanceDecision,
    InvoiceStatus,
    ValidationReport,
    ValidationStatus,
)


# ---------------------------------------------------------------------------
# Thresholds (configurable)
# ---------------------------------------------------------------------------

OCR_CONFIDENCE_THRESHOLD = 0.85       # below this: human verification
AGENT_CONFIDENCE_THRESHOLD = 0.70     # below this: escalate to human
VARIANCE_THRESHOLD_PCT = 0.10         # 10% PO variance triggers investigation
MATERIALITY_L1 = Decimal("5000")      # L1 manager approval
MATERIALITY_L2 = Decimal("25000")     # L2 controller approval
MATERIALITY_L3 = Decimal("100000")    # L3 VP/CFO approval
DUPLICATE_LOOKBACK_DAYS = 90


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _make_audit_entry(
    invoice_id: str,
    event_type: str,
    actor: str,
    description: str,
    before_state: Optional[dict] = None,
    after_state: Optional[dict] = None,
    metadata: Optional[dict] = None,
) -> dict[str, Any]:
    return {
        "entry_id": str(uuid4()),
        "invoice_id": invoice_id,
        "event_type": event_type,
        "actor": actor,
        "description": description,
        "before_state": json.dumps(before_state) if before_state else None,
        "after_state": json.dumps(after_state) if after_state else None,
        "metadata": json.dumps(metadata or {}),
        "timestamp": datetime.utcnow().isoformat(),
    }


def _make_gov_decision(
    invoice_id: str,
    rule: str,
    decision: str,
    reason: str,
    actor: AgentRole,
    escalation: EscalationLevel = EscalationLevel.NONE,
    threshold: Optional[float] = None,
    actual: Optional[float] = None,
) -> dict[str, Any]:
    return {
        "decision_id": str(uuid4()),
        "invoice_id": invoice_id,
        "rule_triggered": rule,
        "decision": decision,
        "escalation_level": escalation.value,
        "reason": reason,
        "actor": actor.value,
        "threshold_value": threshold,
        "actual_value": actual,
        "timestamp": datetime.utcnow().isoformat(),
    }


def _persist(gov_decision: dict[str, Any], audit_entry: dict[str, Any]) -> None:
    save_governance_decision(gov_decision)
    append_audit_entry(audit_entry)


# ---------------------------------------------------------------------------
# Individual rule evaluators
# ---------------------------------------------------------------------------


def evaluate_ocr_confidence(invoice: ExtractedInvoice) -> Optional[GovernanceDecision]:
    """
    Gate 1: If OCR was used and confidence is below threshold, block for human review.
    This prevents low-quality extractions from propagating through the pipeline.
    """
    if invoice.ocr_used and invoice.ocr_confidence < OCR_CONFIDENCE_THRESHOLD:
        decision = GovernanceDecision(
            invoice_id=invoice.invoice_id,
            rule_triggered="ocr_confidence_gate",
            decision="escalate",
            escalation_level=EscalationLevel.HUMAN_REVIEW,
            reason=(
                f"OCR confidence {invoice.ocr_confidence:.1%} is below the "
                f"{OCR_CONFIDENCE_THRESHOLD:.0%} threshold. Manual verification required."
            ),
            actor=AgentRole.DOCUMENT_INTAKE,
            threshold_value=OCR_CONFIDENCE_THRESHOLD,
            actual_value=invoice.ocr_confidence,
        )
        gov_dict = _make_gov_decision(
            str(invoice.invoice_id),
            "ocr_confidence_gate",
            "escalate",
            decision.reason,
            AgentRole.DOCUMENT_INTAKE,
            EscalationLevel.HUMAN_REVIEW,
            OCR_CONFIDENCE_THRESHOLD,
            invoice.ocr_confidence,
        )
        audit = _make_audit_entry(
            str(invoice.invoice_id),
            "governance.ocr_confidence_gate",
            AgentRole.DOCUMENT_INTAKE.value,
            decision.reason,
            metadata={"ocr_confidence": invoice.ocr_confidence},
        )
        _persist(gov_dict, audit)
        return decision
    return None


def evaluate_duplicate(invoice: ExtractedInvoice) -> Optional[GovernanceDecision]:
    """
    Gate 2: Block if an identical invoice (same number + vendor) was processed
    within the last 90 days.
    """
    if not invoice.invoice_number or not invoice.vendor_name:
        return None

    existing = check_duplicate_invoice(
        invoice.invoice_number,
        invoice.vendor_name,
        within_days=DUPLICATE_LOOKBACK_DAYS,
    )
    if existing:
        decision_reason = (
            f"Duplicate detected: invoice {invoice.invoice_number} from "
            f"'{invoice.vendor_name}' already processed (ID: {existing['invoice_id']}) "
            f"within {DUPLICATE_LOOKBACK_DAYS} days."
        )
        gov_dict = _make_gov_decision(
            str(invoice.invoice_id),
            "duplicate_detection",
            "block",
            decision_reason,
            AgentRole.ANOMALY_DETECTION,
            EscalationLevel.HUMAN_REVIEW,
        )
        audit = _make_audit_entry(
            str(invoice.invoice_id),
            "governance.duplicate_detection",
            AgentRole.ANOMALY_DETECTION.value,
            decision_reason,
            metadata={"existing_invoice_id": existing["invoice_id"]},
        )
        _persist(gov_dict, audit)
        return GovernanceDecision(
            invoice_id=invoice.invoice_id,
            rule_triggered="duplicate_detection",
            decision="block",
            escalation_level=EscalationLevel.HUMAN_REVIEW,
            reason=decision_reason,
            actor=AgentRole.ANOMALY_DETECTION,
        )
    return None


def evaluate_unknown_vendor(invoice: ExtractedInvoice) -> Optional[GovernanceDecision]:
    """
    Gate 3: Hold invoices from vendors not in the approved registry.
    Prevents payment to unverified counterparties.
    """
    if not invoice.vendor_name:
        reason = "Vendor name could not be extracted. Invoice held for manual review."
        gov_dict = _make_gov_decision(
            str(invoice.invoice_id),
            "unknown_vendor",
            "escalate",
            reason,
            AgentRole.VALIDATION,
            EscalationLevel.HUMAN_REVIEW,
        )
        audit = _make_audit_entry(
            str(invoice.invoice_id),
            "governance.unknown_vendor",
            AgentRole.VALIDATION.value,
            reason,
        )
        _persist(gov_dict, audit)
        return GovernanceDecision(
            invoice_id=invoice.invoice_id,
            rule_triggered="unknown_vendor",
            decision="escalate",
            escalation_level=EscalationLevel.HUMAN_REVIEW,
            reason=reason,
            actor=AgentRole.VALIDATION,
        )

    if not is_approved_vendor(invoice.vendor_name):
        reason = (
            f"Vendor '{invoice.vendor_name}' is not in the approved vendor registry. "
            "Payment is held pending vendor onboarding verification."
        )
        gov_dict = _make_gov_decision(
            str(invoice.invoice_id),
            "unknown_vendor",
            "escalate",
            reason,
            AgentRole.VALIDATION,
            EscalationLevel.HUMAN_REVIEW,
        )
        audit = _make_audit_entry(
            str(invoice.invoice_id),
            "governance.unknown_vendor",
            AgentRole.VALIDATION.value,
            reason,
            metadata={"vendor_name": invoice.vendor_name},
        )
        _persist(gov_dict, audit)
        return GovernanceDecision(
            invoice_id=invoice.invoice_id,
            rule_triggered="unknown_vendor",
            decision="escalate",
            escalation_level=EscalationLevel.HUMAN_REVIEW,
            reason=reason,
            actor=AgentRole.VALIDATION,
        )
    return None


def evaluate_po_variance(invoice: ExtractedInvoice) -> Optional[GovernanceDecision]:
    """
    Gate 4: Flag invoices where the extracted amount differs from the PO by more
    than VARIANCE_THRESHOLD_PCT. This catches billing errors and potential fraud.
    """
    if not invoice.po_number or invoice.total is None:
        return None

    po = get_purchase_order(invoice.po_number)
    if not po:
        return None

    po_amount = Decimal(str(po["amount"]))
    if po_amount == 0:
        return None

    variance = abs(invoice.total - po_amount) / po_amount
    if variance > Decimal(str(VARIANCE_THRESHOLD_PCT)):
        reason = (
            f"Invoice total {invoice.total} differs from PO {invoice.po_number} "
            f"amount {po_amount} by {float(variance):.1%}, exceeding the "
            f"{VARIANCE_THRESHOLD_PCT:.0%} threshold."
        )
        gov_dict = _make_gov_decision(
            str(invoice.invoice_id),
            "variance_threshold",
            "flag",
            reason,
            AgentRole.VALIDATION,
            EscalationLevel.HUMAN_REVIEW,
            VARIANCE_THRESHOLD_PCT,
            float(variance),
        )
        audit = _make_audit_entry(
            str(invoice.invoice_id),
            "governance.variance_threshold",
            AgentRole.VALIDATION.value,
            reason,
            metadata={"po_amount": float(po_amount), "invoice_total": float(invoice.total), "variance_pct": float(variance)},
        )
        _persist(gov_dict, audit)
        return GovernanceDecision(
            invoice_id=invoice.invoice_id,
            rule_triggered="variance_threshold",
            decision="flag",
            escalation_level=EscalationLevel.HUMAN_REVIEW,
            reason=reason,
            actor=AgentRole.VALIDATION,
            threshold_value=VARIANCE_THRESHOLD_PCT,
            actual_value=float(variance),
        )
    return None


def evaluate_materiality(invoice: ExtractedInvoice) -> Optional[GovernanceDecision]:
    """
    Gate 5: Route invoices to the correct approval level based on amount.
    This implements the four-eyes principle for high-value transactions.
    """
    if invoice.total is None:
        return None

    amount = invoice.total

    if amount >= MATERIALITY_L3:
        level = EscalationLevel.L3_VP_CFO
        reason = f"Invoice total {amount} meets or exceeds the ${MATERIALITY_L3:,.0f} L3 VP/CFO approval threshold."
    elif amount >= MATERIALITY_L2:
        level = EscalationLevel.L2_CONTROLLER
        reason = f"Invoice total {amount} meets or exceeds the ${MATERIALITY_L2:,.0f} L2 Controller approval threshold."
    elif amount >= MATERIALITY_L1:
        level = EscalationLevel.L1_MANAGER
        reason = f"Invoice total {amount} meets or exceeds the ${MATERIALITY_L1:,.0f} L1 Manager approval threshold."
    else:
        return None

    gov_dict = _make_gov_decision(
        str(invoice.invoice_id),
        "materiality_gate",
        "escalate",
        reason,
        AgentRole.RECONCILIATION,
        level,
        float(MATERIALITY_L1 if level == EscalationLevel.L1_MANAGER else MATERIALITY_L2 if level == EscalationLevel.L2_CONTROLLER else MATERIALITY_L3),
        float(amount),
    )
    audit = _make_audit_entry(
        str(invoice.invoice_id),
        "governance.materiality_gate",
        AgentRole.RECONCILIATION.value,
        reason,
        metadata={"amount": float(amount), "escalation_level": level.value},
    )
    _persist(gov_dict, audit)
    return GovernanceDecision(
        invoice_id=invoice.invoice_id,
        rule_triggered="materiality_gate",
        decision="escalate",
        escalation_level=level,
        reason=reason,
        actor=AgentRole.RECONCILIATION,
        threshold_value=float(amount),
        actual_value=float(amount),
    )


def evaluate_agent_confidence(
    invoice: ExtractedInvoice,
    confidence: float,
    actor: AgentRole,
) -> Optional[GovernanceDecision]:
    """
    Gate 6: Any agent reporting confidence below 0.70 triggers human escalation.
    This ensures pipeline degradation is always caught and surfaced.
    """
    if confidence < AGENT_CONFIDENCE_THRESHOLD:
        reason = (
            f"Agent {actor.value} reported confidence {confidence:.1%}, below the "
            f"{AGENT_CONFIDENCE_THRESHOLD:.0%} threshold. Escalating for human review."
        )
        gov_dict = _make_gov_decision(
            str(invoice.invoice_id),
            "agent_confidence_gate",
            "escalate",
            reason,
            actor,
            EscalationLevel.HUMAN_REVIEW,
            AGENT_CONFIDENCE_THRESHOLD,
            confidence,
        )
        audit = _make_audit_entry(
            str(invoice.invoice_id),
            "governance.agent_confidence_gate",
            actor.value,
            reason,
            metadata={"agent_confidence": confidence},
        )
        _persist(gov_dict, audit)
        return GovernanceDecision(
            invoice_id=invoice.invoice_id,
            rule_triggered="agent_confidence_gate",
            decision="escalate",
            escalation_level=EscalationLevel.HUMAN_REVIEW,
            reason=reason,
            actor=actor,
            threshold_value=AGENT_CONFIDENCE_THRESHOLD,
            actual_value=confidence,
        )
    return None


# ---------------------------------------------------------------------------
# Public orchestrator
# ---------------------------------------------------------------------------


class GovernanceEngine:
    """
    Stateless governance engine that evaluates all applicable rules for a given
    pipeline stage and returns a list of triggered decisions.

    Usage:
        engine = GovernanceEngine()
        decisions = engine.evaluate_post_intake(invoice)
        decisions = engine.evaluate_post_extraction(invoice, agent_confidence)
        decisions = engine.evaluate_post_validation(invoice, validation_report)
    """

    def evaluate_post_intake(
        self, invoice: ExtractedInvoice
    ) -> list[GovernanceDecision]:
        """Run governance after the Document Intake stage."""
        decisions = []
        ocr = evaluate_ocr_confidence(invoice)
        if ocr:
            decisions.append(ocr)
        return decisions

    def evaluate_post_extraction(
        self, invoice: ExtractedInvoice, agent_confidence: float
    ) -> list[GovernanceDecision]:
        """Run governance after the Data Extraction stage."""
        decisions = []

        dup = evaluate_duplicate(invoice)
        if dup:
            decisions.append(dup)

        conf = evaluate_agent_confidence(invoice, agent_confidence, AgentRole.DATA_EXTRACTION)
        if conf:
            decisions.append(conf)

        return decisions

    def evaluate_post_validation(
        self, invoice: ExtractedInvoice, validation_report: ValidationReport
    ) -> list[GovernanceDecision]:
        """Run governance after the Validation stage."""
        decisions = []

        vendor = evaluate_unknown_vendor(invoice)
        if vendor:
            decisions.append(vendor)

        variance = evaluate_po_variance(invoice)
        if variance:
            decisions.append(variance)

        conf = evaluate_agent_confidence(
            invoice, validation_report.validation_confidence, AgentRole.VALIDATION
        )
        if conf:
            decisions.append(conf)

        return decisions

    def evaluate_post_anomaly(
        self, invoice: ExtractedInvoice, anomaly_report: "AnomalyReport", agent_confidence: float
    ) -> list[GovernanceDecision]:
        """Run governance after the Anomaly Detection stage."""
        decisions = []

        mat = evaluate_materiality(invoice)
        if mat:
            decisions.append(mat)

        conf = evaluate_agent_confidence(invoice, agent_confidence, AgentRole.ANOMALY_DETECTION)
        if conf:
            decisions.append(conf)

        return decisions

    def determine_final_status(
        self, decisions: list[GovernanceDecision]
    ) -> InvoiceStatus:
        """Derive the final invoice status from all governance decisions."""
        if not decisions:
            return InvoiceStatus.VALIDATED

        has_block = any(d.decision == "block" for d in decisions)
        has_escalate = any(d.decision in ("escalate", "flag") for d in decisions)

        if has_block:
            return InvoiceStatus.REJECTED
        if has_escalate:
            return InvoiceStatus.ON_HOLD
        return InvoiceStatus.VALIDATED
