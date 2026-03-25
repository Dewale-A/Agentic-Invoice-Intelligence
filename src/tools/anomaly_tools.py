"""
Anomaly detection tools: duplicate detection, outlier analysis, and vendor whitelist checks.

Design decision: anomaly detection uses deterministic rules rather than statistical
models for the reference implementation. This ensures auditability and explainability,
which are core requirements for financial compliance. In production, layering in an
ML-based outlier model is straightforward.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from src.data.database import (
    check_duplicate_invoice,
    get_purchase_order,
    is_approved_vendor,
)
from src.models.schemas import (
    AnomalyFlag,
    AnomalyReport,
    AnomalySeverity,
    ExtractedInvoice,
)


# ---------------------------------------------------------------------------
# Individual anomaly detectors
# ---------------------------------------------------------------------------


def detect_duplicate(invoice: ExtractedInvoice) -> Optional[AnomalyFlag]:
    """
    Detect duplicate invoices: same invoice number + vendor within 90 days.
    Severity: CRITICAL (auto-blocks payment).
    """
    if not invoice.invoice_number or not invoice.vendor_name:
        return None

    existing = check_duplicate_invoice(
        invoice.invoice_number,
        invoice.vendor_name,
        within_days=90,
    )
    if existing:
        return AnomalyFlag(
            anomaly_type="duplicate_invoice",
            severity=AnomalySeverity.CRITICAL,
            description=(
                f"Invoice {invoice.invoice_number} from '{invoice.vendor_name}' "
                f"appears to be a duplicate of invoice ID {existing['invoice_id']} "
                f"processed on {existing['created_at']}."
            ),
            evidence={
                "existing_invoice_id": existing["invoice_id"],
                "existing_created_at": existing["created_at"],
                "invoice_number": invoice.invoice_number,
                "vendor_name": invoice.vendor_name,
            },
        )
    return None


def detect_amount_outlier(invoice: ExtractedInvoice) -> Optional[AnomalyFlag]:
    """
    Detect invoices where the amount deviates significantly from the PO.
    Severity is proportional to the deviation magnitude.
    """
    if not invoice.po_number or invoice.total is None:
        return None

    po = get_purchase_order(invoice.po_number)
    if not po:
        return None

    po_amount = Decimal(str(po["amount"]))
    if po_amount == 0:
        return None

    variance = (invoice.total - po_amount) / po_amount
    abs_variance = abs(variance)

    if abs_variance <= Decimal("0.10"):
        return None

    if abs_variance > Decimal("0.50"):
        severity = AnomalySeverity.CRITICAL
    elif abs_variance > Decimal("0.30"):
        severity = AnomalySeverity.HIGH
    elif abs_variance > Decimal("0.15"):
        severity = AnomalySeverity.MEDIUM
    else:
        severity = AnomalySeverity.LOW

    direction = "exceeds" if variance > 0 else "is below"
    return AnomalyFlag(
        anomaly_type="amount_outlier",
        severity=severity,
        description=(
            f"Invoice total {invoice.total} {direction} PO amount {po_amount} "
            f"by {float(abs_variance):.1%} (PO: {invoice.po_number})."
        ),
        evidence={
            "invoice_total": float(invoice.total),
            "po_amount": float(po_amount),
            "variance_pct": float(variance),
            "po_number": invoice.po_number,
        },
    )


def detect_unknown_vendor(invoice: ExtractedInvoice) -> Optional[AnomalyFlag]:
    """
    Flag invoices from vendors not in the approved registry.
    Severity: HIGH (holds payment).
    """
    if not invoice.vendor_name:
        return AnomalyFlag(
            anomaly_type="missing_vendor",
            severity=AnomalySeverity.HIGH,
            description="Vendor name could not be extracted from the invoice.",
            evidence={},
        )

    if not is_approved_vendor(invoice.vendor_name):
        return AnomalyFlag(
            anomaly_type="unknown_vendor",
            severity=AnomalySeverity.HIGH,
            description=(
                f"Vendor '{invoice.vendor_name}' is not in the approved vendor registry. "
                "Payment is held until vendor onboarding is complete."
            ),
            evidence={"vendor_name": invoice.vendor_name},
        )
    return None


def detect_date_anomaly(invoice: ExtractedInvoice) -> Optional[AnomalyFlag]:
    """
    Detect date anomalies: future-dated invoices and stale invoices (>180 days).
    """
    if not invoice.invoice_date:
        return None

    today = date.today()

    # Future-dated
    if invoice.invoice_date > today + timedelta(days=7):
        return AnomalyFlag(
            anomaly_type="future_dated_invoice",
            severity=AnomalySeverity.HIGH,
            description=(
                f"Invoice date {invoice.invoice_date} is in the future "
                f"(today: {today}). This may indicate fraud or a data entry error."
            ),
            evidence={"invoice_date": str(invoice.invoice_date), "today": str(today)},
        )

    # Stale invoice (>180 days old)
    if invoice.invoice_date < today - timedelta(days=180):
        return AnomalyFlag(
            anomaly_type="stale_invoice",
            severity=AnomalySeverity.MEDIUM,
            description=(
                f"Invoice date {invoice.invoice_date} is more than 180 days in the past. "
                "This may indicate a late submission or a resubmission of a previously paid invoice."
            ),
            evidence={"invoice_date": str(invoice.invoice_date), "today": str(today), "age_days": (today - invoice.invoice_date).days},
        )
    return None


def detect_round_number_anomaly(invoice: ExtractedInvoice) -> Optional[AnomalyFlag]:
    """
    Flag invoices with suspiciously round totals (possible fabrication indicator).
    Severity: LOW (informational only).
    """
    if invoice.total is None:
        return None

    # Check if total is a round number (no cents) above $1000
    if invoice.total >= Decimal("1000") and invoice.total % 1 == 0:
        return AnomalyFlag(
            anomaly_type="round_number_amount",
            severity=AnomalySeverity.LOW,
            description=(
                f"Invoice total {invoice.total} is a suspiciously round number. "
                "This is a low-priority informational flag."
            ),
            evidence={"total": float(invoice.total)},
        )
    return None


def detect_missing_critical_fields(invoice: ExtractedInvoice) -> Optional[AnomalyFlag]:
    """Flag invoices missing fields required for payment processing."""
    missing = []
    if not invoice.invoice_number:
        missing.append("invoice_number")
    if not invoice.vendor_name:
        missing.append("vendor_name")
    if invoice.total is None:
        missing.append("total")
    if not invoice.invoice_date:
        missing.append("invoice_date")

    if not missing:
        return None

    severity = AnomalySeverity.HIGH if len(missing) >= 2 else AnomalySeverity.MEDIUM
    return AnomalyFlag(
        anomaly_type="missing_critical_fields",
        severity=severity,
        description=f"Invoice is missing critical fields required for processing: {', '.join(missing)}.",
        evidence={"missing_fields": missing},
    )


# ---------------------------------------------------------------------------
# Aggregated anomaly detection
# ---------------------------------------------------------------------------


def analyze_anomalies(invoice: ExtractedInvoice) -> AnomalyReport:
    """
    Run all anomaly detectors and produce an aggregated AnomalyReport.

    Risk score formula:
      - Each CRITICAL anomaly: +0.40
      - Each HIGH anomaly: +0.25
      - Each MEDIUM anomaly: +0.10
      - Each LOW anomaly: +0.05
    Capped at 1.0.
    """
    detectors = [
        detect_duplicate,
        detect_amount_outlier,
        detect_unknown_vendor,
        detect_date_anomaly,
        detect_round_number_anomaly,
        detect_missing_critical_fields,
    ]

    anomalies: list[AnomalyFlag] = []
    for detector in detectors:
        flag = detector(invoice)
        if flag:
            anomalies.append(flag)

    # Compute risk score
    severity_weights = {
        AnomalySeverity.CRITICAL: 0.40,
        AnomalySeverity.HIGH: 0.25,
        AnomalySeverity.MEDIUM: 0.10,
        AnomalySeverity.LOW: 0.05,
    }
    risk_score = min(
        sum(severity_weights[a.severity] for a in anomalies), 1.0
    )

    anomaly_types = {a.anomaly_type for a in anomalies}

    return AnomalyReport(
        invoice_id=invoice.invoice_id,
        anomalies=anomalies,
        is_duplicate="duplicate_invoice" in anomaly_types,
        duplicate_of=None,  # set by caller if needed
        amount_outlier="amount_outlier" in anomaly_types,
        unknown_vendor="unknown_vendor" in anomaly_types or "missing_vendor" in anomaly_types,
        date_anomaly="future_dated_invoice" in anomaly_types or "stale_invoice" in anomaly_types,
        overall_risk_score=round(risk_score, 3),
    )
