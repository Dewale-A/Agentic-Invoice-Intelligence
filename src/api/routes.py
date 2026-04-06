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
# Demo Mode Guard
# ---------------------------------------------------------------------------

DEMO_MODE = os.environ.get("DEMO_MODE", "false").lower() in ("true", "1", "yes")


def _check_demo_mode():
    """Block write operations when running in demo mode."""
    if DEMO_MODE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This is a live demo. Write operations are disabled for public access. Visit github.com/Dewale-A/AgenticInvoiceIntelligence for the source code.",
        )


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
    _check_demo_mode()
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
    _check_demo_mode()
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
    _check_demo_mode()
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
# Human Review (Governance Loop Closure)
# ---------------------------------------------------------------------------


@router.get("/reviews/pending", tags=["Human Review"])
def get_pending_reviews_endpoint() -> dict[str, Any]:
    """Get invoices awaiting human review."""
    from src.data.database import get_pending_reviews
    pending = get_pending_reviews()
    return {"total": len(pending), "pending_reviews": pending}


@router.post("/reviews/{invoice_id}/decide", tags=["Human Review"])
def submit_human_decision(
    invoice_id: str,
    reviewer_id: str = Query(..., description="Reviewer identifier"),
    reviewer_name: str = Query(..., description="Reviewer display name"),
    decision: str = Query(..., description="approve | adjust_and_approve | reject | escalate_further"),
    rationale_category: str = Query(..., description="Rationale category"),
    rationale_text: str = Query("", description="One-line rationale explanation"),
) -> dict[str, Any]:
    """Submit a structured human review decision for an escalated invoice.

    Decisions: approve, adjust_and_approve, reject, escalate_further.

    Rationale categories: amount_within_variance, vendor_confirmed_correction,
    po_mismatch_resolved, duplicate_confirmed_void, anomaly_is_legitimate,
    requires_senior_review, policy_exception_granted, other.
    """
    _check_demo_mode()
    from src.data.database import (
        VALID_DECISIONS,
        VALID_RATIONALE_CATEGORIES,
        save_human_decision,
        calculate_consistency_score,
        get_invoice,
        update_invoice_status,
    )
    from uuid import uuid4

    # Validate invoice exists
    invoice = get_invoice(invoice_id)
    if not invoice:
        raise _invoice_not_found(invoice_id)

    # Validate decision
    if decision not in VALID_DECISIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid decision. Must be one of: {', '.join(sorted(VALID_DECISIONS))}",
        )

    # Validate rationale category
    if rationale_category not in VALID_RATIONALE_CATEGORIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid rationale category. Must be one of: {', '.join(sorted(VALID_RATIONALE_CATEGORIES))}",
        )

    # Get the original flag that triggered escalation
    from src.data.database import db_session, DB_PATH
    with db_session(DB_PATH) as conn:
        gov_row = conn.execute(
            """SELECT rule_triggered, actor FROM governance_decisions
               WHERE invoice_id = ? AND escalation_level != 'none'
               ORDER BY timestamp DESC LIMIT 1""",
            (invoice_id,),
        ).fetchone()

    original_flag = gov_row["rule_triggered"] if gov_row else "unknown"
    original_agent = gov_row["actor"] if gov_row else "unknown"

    # Calculate consistency score
    consistency = calculate_consistency_score(original_flag, decision)

    # Save the decision
    decision_record = {
        "decision_id": str(uuid4()),
        "invoice_id": invoice_id,
        "reviewer_id": reviewer_id,
        "reviewer_name": reviewer_name,
        "decision": decision,
        "rationale_category": rationale_category,
        "rationale_text": rationale_text,
        "original_flag": original_flag,
        "original_agent": original_agent,
        "consistency_score": consistency,
        "resolution_time_hours": 0.0,
        "timestamp": datetime.utcnow().isoformat(),
    }
    save_human_decision(decision_record)

    # Update invoice status based on decision
    status_map = {
        "approve": "approved",
        "adjust_and_approve": "approved",
        "reject": "rejected",
        "escalate_further": "on_hold",
    }
    update_invoice_status(invoice_id, status_map[decision])

    return {
        "status": "recorded",
        "decision_id": decision_record["decision_id"],
        "invoice_id": invoice_id,
        "decision": decision,
        "consistency_score": consistency,
        "consistency_note": "Not enough historical data" if consistency < 0 else (
            "Aligned with historical pattern" if consistency > 0.6 else
            "Deviates from historical pattern - flagged for review"
        ),
    }


@router.get("/reviews/history", tags=["Human Review"])
def get_review_history(
    invoice_id: Optional[str] = Query(None),
    reviewer_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    """Get human review decision history with optional filters."""
    from src.data.database import get_human_decisions
    decisions = get_human_decisions(invoice_id=invoice_id, reviewer_id=reviewer_id, limit=limit)
    return {"total": len(decisions), "decisions": decisions}


@router.get("/reviews/consistency", tags=["Human Review"])
def get_consistency_dashboard() -> dict[str, Any]:
    """Get decision pattern analysis and reviewer consistency metrics."""
    from src.data.database import get_decision_patterns, get_human_decisions
    patterns = get_decision_patterns()
    recent = get_human_decisions(limit=100)

    # Get unique reviewers and their consistency
    reviewer_ids = set(d["reviewer_id"] for d in recent)
    reviewer_stats = []
    for rid in reviewer_ids:
        from src.data.database import get_reviewer_consistency
        stats = get_reviewer_consistency(rid)
        reviewer_stats.append(stats)

    return {
        "decision_patterns": patterns,
        "reviewer_stats": reviewer_stats,
        "total_human_decisions": len(recent),
    }


@router.get("/governance/audit-trail/{invoice_id}", tags=["Human Review"])
def get_full_invoice_audit_trail(invoice_id: str) -> dict[str, Any]:
    """Get complete audit trail for an invoice: agent decisions + human decisions."""
    from src.data.database import get_audit_trail, get_human_decisions

    invoice = get_invoice(invoice_id)
    if not invoice:
        raise _invoice_not_found(invoice_id)

    audit_entries = get_audit_trail(invoice_id)
    human_decisions = get_human_decisions(invoice_id=invoice_id)

    return {
        "invoice_id": invoice_id,
        "audit_entries": audit_entries,
        "human_decisions": human_decisions,
        "total_events": len(audit_entries),
        "human_reviews": len(human_decisions),
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
