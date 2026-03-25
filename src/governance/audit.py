"""
Audit trail management for AgenticInvoiceIntelligence.

Design decision: all audit functions are thin wrappers around the database layer,
ensuring consistent entry format and immutability guarantees. No caller can
modify or delete an existing audit entry.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from src.data.database import append_audit_entry, get_audit_trail, get_full_audit_trail
from src.models.schemas import AgentRole, AuditTrailEntry


def log_invoice_received(invoice_id: str, filename: str) -> None:
    entry = {
        "entry_id": str(uuid4()),
        "invoice_id": invoice_id,
        "event_type": "invoice.received",
        "actor": AgentRole.DOCUMENT_INTAKE.value,
        "description": f"Invoice received from file: {filename}",
        "before_state": None,
        "after_state": None,
        "metadata": json.dumps({"filename": filename}),
        "timestamp": datetime.utcnow().isoformat(),
    }
    append_audit_entry(entry)


def log_agent_stage(
    invoice_id: str,
    agent_role: AgentRole,
    stage: str,
    summary: str,
    confidence: float,
    metadata: Optional[dict[str, Any]] = None,
) -> None:
    meta = metadata or {}
    meta["confidence"] = confidence
    entry = {
        "entry_id": str(uuid4()),
        "invoice_id": invoice_id,
        "event_type": f"agent.{stage}",
        "actor": agent_role.value,
        "description": summary,
        "before_state": None,
        "after_state": None,
        "metadata": json.dumps(meta),
        "timestamp": datetime.utcnow().isoformat(),
    }
    append_audit_entry(entry)


def log_status_change(
    invoice_id: str,
    old_status: str,
    new_status: str,
    actor: str,
    reason: str = "",
) -> None:
    entry = {
        "entry_id": str(uuid4()),
        "invoice_id": invoice_id,
        "event_type": "invoice.status_change",
        "actor": actor,
        "description": f"Status changed from '{old_status}' to '{new_status}'. {reason}".strip(),
        "before_state": json.dumps({"status": old_status}),
        "after_state": json.dumps({"status": new_status}),
        "metadata": json.dumps({"reason": reason}),
        "timestamp": datetime.utcnow().isoformat(),
    }
    append_audit_entry(entry)


def log_human_decision(
    invoice_id: str,
    actor: str,
    decision: str,
    reason: str,
) -> None:
    entry = {
        "entry_id": str(uuid4()),
        "invoice_id": invoice_id,
        "event_type": f"human.{decision}",
        "actor": f"human:{actor}",
        "description": f"Human decision '{decision}' by {actor}: {reason}",
        "before_state": None,
        "after_state": None,
        "metadata": json.dumps({"decision": decision, "reason": reason}),
        "timestamp": datetime.utcnow().isoformat(),
    }
    append_audit_entry(entry)


def get_invoice_audit_trail(invoice_id: str) -> list[AuditTrailEntry]:
    """Return parsed AuditTrailEntry objects for an invoice."""
    rows = get_audit_trail(invoice_id)
    results = []
    for row in rows:
        results.append(
            AuditTrailEntry(
                entry_id=row["entry_id"],
                invoice_id=row["invoice_id"],
                event_type=row["event_type"],
                actor=row["actor"],
                description=row["description"],
                before_state=json.loads(row["before_state"]) if row["before_state"] else None,
                after_state=json.loads(row["after_state"]) if row["after_state"] else None,
                metadata=json.loads(row["metadata"]) if row["metadata"] else {},
                timestamp=datetime.fromisoformat(row["timestamp"]),
            )
        )
    return results


def get_system_audit_trail(limit: int = 200) -> list[dict[str, Any]]:
    """Return raw audit trail rows system-wide."""
    return get_full_audit_trail(limit=limit)
