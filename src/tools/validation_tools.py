"""
Validation tools: PO lookup, vendor registry check, and budget validation.

Design decision: validation is field-level rather than invoice-level, enabling
partial validation where some fields pass and others fail. This provides richer
signals to the governance engine and downstream agents.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from src.data.database import get_purchase_order, get_vendor_by_name, is_approved_vendor
from src.models.schemas import (
    ExtractedInvoice,
    FieldValidationResult,
    ValidationReport,
    ValidationStatus,
)


# ---------------------------------------------------------------------------
# Individual field validators
# ---------------------------------------------------------------------------


def validate_vendor(invoice: ExtractedInvoice) -> FieldValidationResult:
    """Check that the vendor is in the approved registry."""
    if not invoice.vendor_name:
        return FieldValidationResult(
            field_name="vendor_name",
            status=ValidationStatus.FAIL,
            extracted_value=None,
            message="Vendor name is missing.",
            confidence=0.0,
        )

    vendor = get_vendor_by_name(invoice.vendor_name)
    if not vendor:
        return FieldValidationResult(
            field_name="vendor_name",
            status=ValidationStatus.FAIL,
            extracted_value=invoice.vendor_name,
            message=f"Vendor '{invoice.vendor_name}' not found in approved registry.",
            confidence=0.9,
        )

    if not vendor.get("approved"):
        return FieldValidationResult(
            field_name="vendor_name",
            status=ValidationStatus.FAIL,
            extracted_value=invoice.vendor_name,
            message=f"Vendor '{invoice.vendor_name}' exists but is not approved.",
            confidence=0.9,
        )

    return FieldValidationResult(
        field_name="vendor_name",
        status=ValidationStatus.PASS,
        extracted_value=invoice.vendor_name,
        expected_value=vendor["name"],
        message="Vendor is in the approved registry.",
        confidence=1.0,
    )


def validate_po_match(invoice: ExtractedInvoice) -> FieldValidationResult:
    """Cross-reference the PO number and validate the amount matches."""
    if not invoice.po_number:
        return FieldValidationResult(
            field_name="po_number",
            status=ValidationStatus.WARNING,
            extracted_value=None,
            message="No PO number extracted. Manual PO matching required.",
            confidence=0.5,
        )

    po = get_purchase_order(invoice.po_number)
    if not po:
        return FieldValidationResult(
            field_name="po_number",
            status=ValidationStatus.FAIL,
            extracted_value=invoice.po_number,
            message=f"PO '{invoice.po_number}' not found in the system.",
            confidence=0.9,
        )

    po_amount = Decimal(str(po["amount"]))

    if invoice.total is None:
        return FieldValidationResult(
            field_name="po_number",
            status=ValidationStatus.WARNING,
            extracted_value=invoice.po_number,
            expected_value=str(po_amount),
            message="PO found but invoice total is missing. Cannot validate amount.",
            confidence=0.6,
        )

    variance = abs(invoice.total - po_amount) / po_amount if po_amount else Decimal("0")

    if variance > Decimal("0.10"):
        return FieldValidationResult(
            field_name="po_number",
            status=ValidationStatus.FAIL,
            extracted_value=str(invoice.total),
            expected_value=str(po_amount),
            message=(
                f"Invoice total {invoice.total} differs from PO amount {po_amount} "
                f"by {float(variance):.1%}."
            ),
            confidence=0.8,
        )

    return FieldValidationResult(
        field_name="po_number",
        status=ValidationStatus.PASS,
        extracted_value=invoice.po_number,
        expected_value=po["po_number"],
        message=f"PO matched. Amount variance: {float(variance):.2%}.",
        confidence=1.0,
    )


def validate_invoice_date(invoice: ExtractedInvoice) -> FieldValidationResult:
    """Validate invoice date is not in the future (more than 7 days)."""
    from datetime import date, timedelta

    if not invoice.invoice_date:
        return FieldValidationResult(
            field_name="invoice_date",
            status=ValidationStatus.WARNING,
            extracted_value=None,
            message="Invoice date could not be extracted.",
            confidence=0.5,
        )

    today = date.today()
    future_threshold = today + timedelta(days=7)

    if invoice.invoice_date > future_threshold:
        return FieldValidationResult(
            field_name="invoice_date",
            status=ValidationStatus.FAIL,
            extracted_value=str(invoice.invoice_date),
            expected_value=f"<= {today}",
            message=f"Invoice date {invoice.invoice_date} is in the future.",
            confidence=0.95,
        )

    return FieldValidationResult(
        field_name="invoice_date",
        status=ValidationStatus.PASS,
        extracted_value=str(invoice.invoice_date),
        message="Invoice date is valid.",
        confidence=1.0,
    )


def validate_total_arithmetic(invoice: ExtractedInvoice) -> FieldValidationResult:
    """Validate that subtotal + tax = total (within rounding tolerance)."""
    if invoice.subtotal is None or invoice.tax is None or invoice.total is None:
        return FieldValidationResult(
            field_name="total",
            status=ValidationStatus.SKIPPED,
            message="Cannot validate arithmetic: one or more of subtotal/tax/total is missing.",
            confidence=0.5,
        )

    expected = invoice.subtotal + invoice.tax
    diff = abs(expected - invoice.total)

    if diff > Decimal("1.00"):
        return FieldValidationResult(
            field_name="total",
            status=ValidationStatus.FAIL,
            extracted_value=str(invoice.total),
            expected_value=str(expected),
            message=f"Total arithmetic mismatch: {invoice.subtotal} + {invoice.tax} = {expected}, but total is {invoice.total}.",
            confidence=0.9,
        )

    return FieldValidationResult(
        field_name="total",
        status=ValidationStatus.PASS,
        extracted_value=str(invoice.total),
        expected_value=str(expected),
        message="Total arithmetic is consistent.",
        confidence=1.0,
    )


def validate_currency(invoice: ExtractedInvoice) -> FieldValidationResult:
    """Validate currency is an accepted code."""
    allowed = {"USD", "CAD", "EUR", "GBP", "AUD", "JPY", "CHF"}
    if invoice.currency not in allowed:
        return FieldValidationResult(
            field_name="currency",
            status=ValidationStatus.FAIL,
            extracted_value=invoice.currency,
            message=f"Currency '{invoice.currency}' is not in the accepted list: {allowed}.",
            confidence=0.9,
        )
    return FieldValidationResult(
        field_name="currency",
        status=ValidationStatus.PASS,
        extracted_value=invoice.currency,
        message="Currency code is valid.",
        confidence=1.0,
    )


# ---------------------------------------------------------------------------
# Aggregated validation
# ---------------------------------------------------------------------------


def validate_invoice(invoice: ExtractedInvoice) -> ValidationReport:
    """
    Run all validation checks and produce an aggregated ValidationReport.

    The validation_confidence score is the mean of all field-level confidence
    scores, weighted toward failed checks.
    """
    results = [
        validate_vendor(invoice),
        validate_po_match(invoice),
        validate_invoice_date(invoice),
        validate_total_arithmetic(invoice),
        validate_currency(invoice),
    ]

    failed = [r for r in results if r.status == ValidationStatus.FAIL]
    warnings = [r for r in results if r.status == ValidationStatus.WARNING]

    if failed:
        overall = ValidationStatus.FAIL
    elif warnings:
        overall = ValidationStatus.WARNING
    else:
        overall = ValidationStatus.PASS

    # Compute PO variance for reporting
    po_variance_pct: Optional[float] = None
    po_match = False
    if invoice.po_number and invoice.total:
        po = get_purchase_order(invoice.po_number)
        if po:
            po_amount = Decimal(str(po["amount"]))
            if po_amount:
                variance = float(abs(invoice.total - po_amount) / po_amount)
                po_variance_pct = round(variance, 4)
                po_match = variance <= 0.10

    vendor_approved = is_approved_vendor(invoice.vendor_name or "")

    # Aggregate confidence
    confidences = [r.confidence for r in results]
    validation_confidence = round(sum(confidences) / len(confidences), 3)

    return ValidationReport(
        invoice_id=invoice.invoice_id,
        overall_status=overall,
        field_results=results,
        po_match=po_match,
        po_variance_pct=po_variance_pct,
        vendor_approved=vendor_approved,
        validation_confidence=validation_confidence,
    )
