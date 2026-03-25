"""
FastAPI routes for the AgenticInvoiceIntelligence API.

Design decision: the API layer is thin. It validates inputs, delegates to the
processing pipeline, and serializes outputs. No business logic lives here.
All processing decisions and governance rules are in the crew/governance layer.

13 endpoints:
  POST   /invoices/upload
  GET    /invoices
  GET    /invoices/{id}
  GET    /invoices/{id}/audit
  POST   /invoices/{id}/approve
  POST   /invoices/{id}/reject
  GET    /reconciliation/report
  GET    /reconciliation/exceptions
  GET    /governance/dashboard
  GET    /governance/audit-trail
  GET    /vendors
  GET    /purchase-orders
  GET    /health
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, UploadFile, status
from fastapi.responses import JSONResponse

from src.data.database import (
    bootstrap,
    get_governance_stats,
    get_invoice,
    get_vendor_by_name,
    list_invoices,
    list_purchase_orders,
    list_vendors,
    update_invoice_status,
)
from src.governance.audit import (
    get_invoice_audit_trail,
    get_system_audit_trail,
    log_human_decision,
    log_status_change,
)
from src.models.schemas import (
    GovernanceDashboard,
    InvoiceApprovalRequest,
    InvoiceRejectionRequest,
    InvoiceStatus,
    InvoiceUploadResponse,
    PurchaseOrder,
    ReconciliationItem,
    ReconciliationReport,
    VendorRecord,
)

router = APIRouter()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _invoice_not_found(invoice_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Invoice '{invoice_id}' not found.",
    )


def _decimal_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@router.get("/health", tags=["System"])
def health_check() -> dict[str, Any]:
    """System health check. Returns service status and database connectivity."""
    try:
        bootstrap()
        vendors = list_vendors()
        return {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "database": "connected",
            "vendor_count": len(vendors),
        }
    except Exception as exc:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unhealthy", "error": str(exc)},
        )


# ---------------------------------------------------------------------------
# Invoice upload and processing
# ---------------------------------------------------------------------------


@router.post(
    "/invoices/upload",
    response_model=InvoiceUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Invoices"],
)
async def upload_invoice(
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
) -> InvoiceUploadResponse:
    """
    Upload a PDF invoice for processing.

    The invoice is processed synchronously through the full 5-agent pipeline.
    For production use, replace with an async queue (Celery, SQS, etc.).
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are accepted.",
        )

    # Save to a temporary file
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        from src.crew import InvoiceProcessingCrew

        crew = InvoiceProcessingCrew()
        invoice, anomaly_report, gov_decisions = crew.process_invoice(tmp_path)

        return InvoiceUploadResponse(
            invoice_id=invoice.invoice_id,
            filename=file.filename,
            status=invoice.status,
            message=(
                f"Invoice processed. Status: {invoice.status.value}. "
                f"{len(gov_decisions)} governance rule(s) triggered. "
                f"{len(anomaly_report.anomalies)} anomaly flag(s)."
            ),
        )
    finally:
        tmp_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Invoice retrieval
# ---------------------------------------------------------------------------


@router.get("/invoices", tags=["Invoices"])
def list_invoices_endpoint(
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """List all invoices with optional status filter and pagination."""
    invoices = list_invoices(status=status_filter, limit=limit, offset=offset)
    return {
        "total": len(invoices),
        "limit": limit,
        "offset": offset,
        "invoices": invoices,
    }


@router.get("/invoices/{invoice_id}", tags=["Invoices"])
def get_invoice_endpoint(invoice_id: str) -> dict[str, Any]:
    """Retrieve a single invoice by ID."""
    invoice = get_invoice(invoice_id)
    if not invoice:
        raise _invoice_not_found(invoice_id)
    return invoice


@router.get("/invoices/{invoice_id}/audit", tags=["Invoices"])
def get_invoice_audit(invoice_id: str) -> dict[str, Any]:
    """Retrieve the full audit trail for a specific invoice."""
    invoice = get_invoice(invoice_id)
    if not invoice:
        raise _invoice_not_found(invoice_id)

    trail = get_invoice_audit_trail(invoice_id)
    return {
        "invoice_id": invoice_id,
        "audit_trail": [e.model_dump(mode="json") for e in trail],
        "total_entries": len(trail),
    }


# ---------------------------------------------------------------------------
# Approval / rejection
# ---------------------------------------------------------------------------


@router.post("/invoices/{invoice_id}/approve", tags=["Invoices"])
def approve_invoice(invoice_id: str, request: InvoiceApprovalRequest) -> dict[str, Any]:
    """
    Manually approve an invoice.

    Only invoices in PENDING, PROCESSING, VALIDATED, FLAGGED, or ON_HOLD status
    can be approved. REJECTED invoices require a new submission.
    """
    invoice = get_invoice(invoice_id)
    if not invoice:
        raise _invoice_not_found(invoice_id)

    approvable_statuses = {
        InvoiceStatus.PENDING.value,
        InvoiceStatus.PROCESSING.value,
        InvoiceStatus.VALIDATED.value,
        InvoiceStatus.FLAGGED.value,
        InvoiceStatus.ON_HOLD.value,
    }
    if invoice["status"] not in approvable_statuses:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot approve invoice in '{invoice['status']}' status.",
        )

    old_status = invoice["status"]
    update_invoice_status(invoice_id, InvoiceStatus.APPROVED.value)
    log_status_change(
        invoice_id,
        old_status,
        InvoiceStatus.APPROVED.value,
        f"human:{request.approved_by}",
        request.notes,
    )
    log_human_decision(invoice_id, request.approved_by, "approve", request.notes)

    return {
        "invoice_id": invoice_id,
        "status": InvoiceStatus.APPROVED.value,
        "approved_by": request.approved_by,
        "message": "Invoice approved successfully.",
    }


@router.post("/invoices/{invoice_id}/reject", tags=["Invoices"])
def reject_invoice(invoice_id: str, request: InvoiceRejectionRequest) -> dict[str, Any]:
    """Manually reject an invoice."""
    invoice = get_invoice(invoice_id)
    if not invoice:
        raise _invoice_not_found(invoice_id)

    if invoice["status"] == InvoiceStatus.APPROVED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot reject an already-approved invoice.",
        )

    old_status = invoice["status"]
    update_invoice_status(invoice_id, InvoiceStatus.REJECTED.value)
    log_status_change(
        invoice_id,
        old_status,
        InvoiceStatus.REJECTED.value,
        f"human:{request.rejected_by}",
        request.reason,
    )
    log_human_decision(invoice_id, request.rejected_by, "reject", request.reason)

    return {
        "invoice_id": invoice_id,
        "status": InvoiceStatus.REJECTED.value,
        "rejected_by": request.rejected_by,
        "reason": request.reason,
        "message": "Invoice rejected.",
    }


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


@router.get("/reconciliation/report", tags=["Reconciliation"])
def get_reconciliation_report() -> dict[str, Any]:
    """Generate a reconciliation report for all invoices."""
    all_invoices = list_invoices(limit=1000)

    from decimal import Decimal as D

    report = {
        "generated_at": datetime.utcnow().isoformat(),
        "total_invoices": len(all_invoices),
        "by_status": {},
        "total_value": 0.0,
        "flagged_value": 0.0,
        "invoices": all_invoices,
    }

    for inv in all_invoices:
        st = inv.get("status", "unknown")
        report["by_status"][st] = report["by_status"].get(st, 0) + 1
        total = inv.get("total") or 0
        report["total_value"] += total
        if st in ("flagged", "on_hold", "rejected"):
            report["flagged_value"] += total

    return report


@router.get("/reconciliation/exceptions", tags=["Reconciliation"])
def get_reconciliation_exceptions() -> dict[str, Any]:
    """Return all invoices requiring human review (flagged, on_hold, rejected)."""
    exceptions = []
    for st in ("flagged", "on_hold", "rejected"):
        exceptions.extend(list_invoices(status=st, limit=500))

    return {
        "total_exceptions": len(exceptions),
        "exceptions": exceptions,
    }


# ---------------------------------------------------------------------------
# Governance
# ---------------------------------------------------------------------------


@router.get("/governance/dashboard", response_model=GovernanceDashboard, tags=["Governance"])
def get_governance_dashboard() -> GovernanceDashboard:
    """Return the governance dashboard with KPIs and rule trigger counts."""
    stats = get_governance_stats()
    return GovernanceDashboard(**stats)


@router.get("/governance/audit-trail", tags=["Governance"])
def get_governance_audit_trail(
    limit: int = Query(200, ge=1, le=1000)
) -> dict[str, Any]:
    """Return the system-wide immutable audit trail."""
    entries = get_system_audit_trail(limit=limit)
    return {
        "total_entries": len(entries),
        "entries": entries,
    }


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------


@router.get("/vendors", tags=["Reference Data"])
def get_vendors() -> dict[str, Any]:
    """List all approved vendors."""
    vendors = list_vendors()
    return {"total": len(vendors), "vendors": vendors}


@router.get("/purchase-orders", tags=["Reference Data"])
def get_purchase_orders() -> dict[str, Any]:
    """List all purchase orders."""
    pos = list_purchase_orders()
    return {"total": len(pos), "purchase_orders": pos}
