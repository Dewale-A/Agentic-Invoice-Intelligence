"""
SQLite database layer for AgenticInvoiceIntelligence.

Design decision: SQLite is used for the reference/demo implementation because it
requires zero infrastructure. In production, replace with PostgreSQL and use
SQLAlchemy's async engine. The schema and query patterns are identical.

Tables:
  - vendors          : 20 approved vendor records
  - purchase_orders  : 15 PO records with expected amounts
  - invoices         : processed invoice records
  - audit_log        : immutable append-only audit trail
  - governance_decisions : governance engine decisions
  - agent_decisions  : per-agent confidence and output log
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Generator, Optional
from uuid import uuid4

DB_PATH = Path(__file__).parent / "invoice_intelligence.db"

# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Return a SQLite connection with row_factory and foreign keys enabled."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def db_session(db_path: Path = DB_PATH) -> Generator[sqlite3.Connection, None, None]:
    """Context manager for a database session with automatic commit/rollback."""
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Schema creation
# ---------------------------------------------------------------------------

DDL = """
CREATE TABLE IF NOT EXISTS vendors (
    vendor_id        TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    category         TEXT NOT NULL,
    contracted_rate  REAL,
    payment_terms_days INTEGER DEFAULT 30,
    approved         INTEGER DEFAULT 1,
    contact_email    TEXT,
    created_at       TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS purchase_orders (
    po_number        TEXT PRIMARY KEY,
    vendor_id        TEXT NOT NULL REFERENCES vendors(vendor_id),
    vendor_name      TEXT NOT NULL,
    description      TEXT NOT NULL,
    amount           REAL NOT NULL,
    currency         TEXT DEFAULT 'USD',
    issued_date      TEXT NOT NULL,
    expiry_date      TEXT,
    remaining_balance REAL,
    status           TEXT DEFAULT 'open',
    created_at       TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS invoices (
    invoice_id           TEXT PRIMARY KEY,
    source_filename      TEXT NOT NULL,
    document_type        TEXT DEFAULT 'invoice',
    vendor_name          TEXT,
    vendor_id            TEXT,
    invoice_number       TEXT,
    invoice_date         TEXT,
    due_date             TEXT,
    po_number            TEXT,
    currency             TEXT DEFAULT 'USD',
    subtotal             REAL,
    tax                  REAL,
    total                REAL,
    line_items_json      TEXT DEFAULT '[]',
    extraction_confidence REAL DEFAULT 0.0,
    ocr_confidence       REAL DEFAULT 1.0,
    ocr_used             INTEGER DEFAULT 0,
    status               TEXT DEFAULT 'pending',
    created_at           TEXT DEFAULT (datetime('now')),
    updated_at           TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS audit_log (
    entry_id        TEXT PRIMARY KEY,
    invoice_id      TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    actor           TEXT NOT NULL,
    description     TEXT NOT NULL,
    before_state    TEXT,
    after_state     TEXT,
    metadata        TEXT DEFAULT '{}',
    timestamp       TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS governance_decisions (
    decision_id      TEXT PRIMARY KEY,
    invoice_id       TEXT NOT NULL,
    rule_triggered   TEXT NOT NULL,
    decision         TEXT NOT NULL,
    escalation_level TEXT DEFAULT 'none',
    reason           TEXT NOT NULL,
    actor            TEXT NOT NULL,
    threshold_value  REAL,
    actual_value     REAL,
    timestamp        TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS agent_decisions (
    decision_id          TEXT PRIMARY KEY,
    invoice_id           TEXT NOT NULL,
    agent_role           TEXT NOT NULL,
    stage_input_summary  TEXT DEFAULT '',
    stage_output_summary TEXT DEFAULT '',
    confidence           REAL DEFAULT 1.0,
    escalated            INTEGER DEFAULT 0,
    escalation_reason    TEXT,
    processing_time_ms   INTEGER,
    timestamp            TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS human_decisions (
    decision_id      TEXT PRIMARY KEY,
    invoice_id       TEXT NOT NULL,
    reviewer_id      TEXT NOT NULL,
    reviewer_name    TEXT NOT NULL,
    decision         TEXT NOT NULL,
    rationale_category TEXT NOT NULL,
    rationale_text   TEXT DEFAULT '',
    original_flag    TEXT NOT NULL,
    original_agent   TEXT DEFAULT '',
    consistency_score REAL DEFAULT -1.0,
    resolution_time_hours REAL DEFAULT 0.0,
    timestamp        TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS decision_patterns (
    pattern_id       TEXT PRIMARY KEY,
    flag_type        TEXT NOT NULL,
    total_decisions  INTEGER DEFAULT 0,
    approve_count    INTEGER DEFAULT 0,
    reject_count     INTEGER DEFAULT 0,
    adjust_count     INTEGER DEFAULT 0,
    escalate_count   INTEGER DEFAULT 0,
    avg_resolution_hours REAL DEFAULT 0.0,
    last_updated     TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status);
CREATE INDEX IF NOT EXISTS idx_invoices_vendor ON invoices(vendor_id);
CREATE INDEX IF NOT EXISTS idx_audit_invoice ON audit_log(invoice_id);
CREATE INDEX IF NOT EXISTS idx_gov_invoice ON governance_decisions(invoice_id);
CREATE INDEX IF NOT EXISTS idx_agent_invoice ON agent_decisions(invoice_id);
CREATE INDEX IF NOT EXISTS idx_human_invoice ON human_decisions(invoice_id);
CREATE INDEX IF NOT EXISTS idx_human_reviewer ON human_decisions(reviewer_id);
CREATE INDEX IF NOT EXISTS idx_patterns_flag ON decision_patterns(flag_type);
"""


def init_db(db_path: Path = DB_PATH) -> None:
    """Initialize the database schema."""
    conn = get_connection(db_path)
    try:
        conn.executescript(DDL)
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Seed data: 20 vendors
# ---------------------------------------------------------------------------

VENDORS: list[dict[str, Any]] = [
    {"vendor_id": "VND001", "name": "Acme Cloud Services", "category": "Technology", "contracted_rate": 15000.00, "payment_terms_days": 30, "contact_email": "billing@acmecloud.com"},
    {"vendor_id": "VND002", "name": "BrightPath Consulting", "category": "Professional Services", "contracted_rate": 25000.00, "payment_terms_days": 45, "contact_email": "accounts@brightpath.com"},
    {"vendor_id": "VND003", "name": "CoreNet Networking", "category": "Infrastructure", "contracted_rate": 8000.00, "payment_terms_days": 30, "contact_email": "ap@corenet.io"},
    {"vendor_id": "VND004", "name": "DataVault Storage", "category": "Technology", "contracted_rate": 5500.00, "payment_terms_days": 30, "contact_email": "billing@datavault.com"},
    {"vendor_id": "VND005", "name": "EagleEye Security", "category": "Security", "contracted_rate": 12000.00, "payment_terms_days": 30, "contact_email": "invoices@eagleeye.com"},
    {"vendor_id": "VND006", "name": "FlexStaff Recruitment", "category": "Staffing", "contracted_rate": 35000.00, "payment_terms_days": 14, "contact_email": "billing@flexstaff.com"},
    {"vendor_id": "VND007", "name": "GreenLeaf Facilities", "category": "Facilities", "contracted_rate": 3500.00, "payment_terms_days": 30, "contact_email": "ar@greenleaf.com"},
    {"vendor_id": "VND008", "name": "HighTower Analytics", "category": "Analytics", "contracted_rate": 18000.00, "payment_terms_days": 30, "contact_email": "billing@hightower.ai"},
    {"vendor_id": "VND009", "name": "IronClad Legal", "category": "Legal", "contracted_rate": 22000.00, "payment_terms_days": 60, "contact_email": "accounts@ironclad.law"},
    {"vendor_id": "VND010", "name": "JetPrint Marketing", "category": "Marketing", "contracted_rate": 9000.00, "payment_terms_days": 30, "contact_email": "billing@jetprint.com"},
    {"vendor_id": "VND011", "name": "KeyStone Audit", "category": "Audit", "contracted_rate": 28000.00, "payment_terms_days": 45, "contact_email": "invoices@keystone-audit.com"},
    {"vendor_id": "VND012", "name": "LumaDesign Creative", "category": "Creative", "contracted_rate": 7500.00, "payment_terms_days": 30, "contact_email": "billing@lumadesign.com"},
    {"vendor_id": "VND013", "name": "MicroSafe Compliance", "category": "Compliance", "contracted_rate": 14000.00, "payment_terms_days": 30, "contact_email": "ap@microsafe.com"},
    {"vendor_id": "VND014", "name": "NexGen Software", "category": "Technology", "contracted_rate": 45000.00, "payment_terms_days": 30, "contact_email": "billing@nexgen.dev"},
    {"vendor_id": "VND015", "name": "OmegaFleet Logistics", "category": "Logistics", "contracted_rate": 6000.00, "payment_terms_days": 14, "contact_email": "billing@omegafleet.com"},
    {"vendor_id": "VND016", "name": "PinnacleHR Solutions", "category": "HR", "contracted_rate": 11000.00, "payment_terms_days": 30, "contact_email": "accounts@pinnaclehr.com"},
    {"vendor_id": "VND017", "name": "QuantumPrint Office", "category": "Office Supplies", "contracted_rate": 2000.00, "payment_terms_days": 30, "contact_email": "billing@quantumprint.com"},
    {"vendor_id": "VND018", "name": "RapidCloud Hosting", "category": "Technology", "contracted_rate": 20000.00, "payment_terms_days": 30, "contact_email": "billing@rapidcloud.com"},
    {"vendor_id": "VND019", "name": "SterlingPay Payroll", "category": "Payroll", "contracted_rate": 8500.00, "payment_terms_days": 30, "contact_email": "ap@sterlingpay.com"},
    {"vendor_id": "VND020", "name": "TrueNorth Training", "category": "Training", "contracted_rate": 5000.00, "payment_terms_days": 30, "contact_email": "billing@truenorth.ca"},
]

# ---------------------------------------------------------------------------
# Seed data: 15 purchase orders
# ---------------------------------------------------------------------------

PURCHASE_ORDERS: list[dict[str, Any]] = [
    {"po_number": "PO-2024-001", "vendor_id": "VND001", "vendor_name": "Acme Cloud Services", "description": "Annual cloud infrastructure subscription Q1", "amount": 15000.00, "issued_date": "2024-01-01", "expiry_date": "2024-03-31", "remaining_balance": 15000.00},
    {"po_number": "PO-2024-002", "vendor_id": "VND002", "vendor_name": "BrightPath Consulting", "description": "Digital transformation consulting engagement", "amount": 25000.00, "issued_date": "2024-01-15", "expiry_date": "2024-06-30", "remaining_balance": 25000.00},
    {"po_number": "PO-2024-003", "vendor_id": "VND003", "vendor_name": "CoreNet Networking", "description": "Network infrastructure upgrade phase 1", "amount": 8000.00, "issued_date": "2024-02-01", "expiry_date": "2024-04-30", "remaining_balance": 8000.00},
    {"po_number": "PO-2024-004", "vendor_id": "VND004", "vendor_name": "DataVault Storage", "description": "Backup storage expansion 50TB", "amount": 5500.00, "issued_date": "2024-02-15", "expiry_date": "2024-05-31", "remaining_balance": 5500.00},
    {"po_number": "PO-2024-005", "vendor_id": "VND005", "vendor_name": "EagleEye Security", "description": "Penetration testing and security audit", "amount": 12000.00, "issued_date": "2024-03-01", "expiry_date": "2024-05-31", "remaining_balance": 12000.00},
    {"po_number": "PO-2024-006", "vendor_id": "VND006", "vendor_name": "FlexStaff Recruitment", "description": "Contract staffing Q1 developer resources", "amount": 35000.00, "issued_date": "2024-01-01", "expiry_date": "2024-03-31", "remaining_balance": 35000.00},
    {"po_number": "PO-2024-007", "vendor_id": "VND007", "vendor_name": "GreenLeaf Facilities", "description": "Monthly office cleaning and maintenance", "amount": 3500.00, "issued_date": "2024-03-01", "expiry_date": "2024-03-31", "remaining_balance": 3500.00},
    {"po_number": "PO-2024-008", "vendor_id": "VND008", "vendor_name": "HighTower Analytics", "description": "BI dashboard development and licensing", "amount": 18000.00, "issued_date": "2024-02-01", "expiry_date": "2024-07-31", "remaining_balance": 18000.00},
    {"po_number": "PO-2024-009", "vendor_id": "VND009", "vendor_name": "IronClad Legal", "description": "Contract review and compliance advisory", "amount": 22000.00, "issued_date": "2024-01-15", "expiry_date": "2024-06-30", "remaining_balance": 22000.00},
    {"po_number": "PO-2024-010", "vendor_id": "VND010", "vendor_name": "JetPrint Marketing", "description": "Q1 digital marketing campaign", "amount": 9000.00, "issued_date": "2024-01-01", "expiry_date": "2024-03-31", "remaining_balance": 9000.00},
    {"po_number": "PO-2024-011", "vendor_id": "VND011", "vendor_name": "KeyStone Audit", "description": "Annual internal audit services", "amount": 28000.00, "issued_date": "2024-01-15", "expiry_date": "2024-12-31", "remaining_balance": 28000.00},
    {"po_number": "PO-2024-012", "vendor_id": "VND013", "vendor_name": "MicroSafe Compliance", "description": "SOC 2 Type II readiness assessment", "amount": 14000.00, "issued_date": "2024-02-15", "expiry_date": "2024-08-31", "remaining_balance": 14000.00},
    {"po_number": "PO-2024-013", "vendor_id": "VND014", "vendor_name": "NexGen Software", "description": "ERP integration middleware license", "amount": 45000.00, "issued_date": "2024-01-01", "expiry_date": "2024-12-31", "remaining_balance": 45000.00},
    {"po_number": "PO-2024-014", "vendor_id": "VND018", "vendor_name": "RapidCloud Hosting", "description": "Managed hosting services H1 2024", "amount": 20000.00, "issued_date": "2024-01-01", "expiry_date": "2024-06-30", "remaining_balance": 20000.00},
    {"po_number": "PO-2024-015", "vendor_id": "VND020", "vendor_name": "TrueNorth Training", "description": "Staff upskilling program Q1", "amount": 5000.00, "issued_date": "2024-02-01", "expiry_date": "2024-04-30", "remaining_balance": 5000.00},
]


def seed_db(db_path: Path = DB_PATH) -> None:
    """Seed the database with vendors and purchase orders if empty."""
    with db_session(db_path) as conn:
        existing = conn.execute("SELECT COUNT(*) FROM vendors").fetchone()[0]
        if existing > 0:
            return

        for v in VENDORS:
            conn.execute(
                """INSERT OR IGNORE INTO vendors
                   (vendor_id, name, category, contracted_rate, payment_terms_days, approved, contact_email)
                   VALUES (:vendor_id, :name, :category, :contracted_rate, :payment_terms_days, 1, :contact_email)""",
                v,
            )

        for po in PURCHASE_ORDERS:
            conn.execute(
                """INSERT OR IGNORE INTO purchase_orders
                   (po_number, vendor_id, vendor_name, description, amount, currency, issued_date, expiry_date, remaining_balance, status)
                   VALUES (:po_number, :vendor_id, :vendor_name, :description, :amount, 'USD', :issued_date, :expiry_date, :remaining_balance, 'open')""",
                po,
            )


# ---------------------------------------------------------------------------
# Vendor queries
# ---------------------------------------------------------------------------


def get_vendor(vendor_id: str, db_path: Path = DB_PATH) -> Optional[dict[str, Any]]:
    with db_session(db_path) as conn:
        row = conn.execute("SELECT * FROM vendors WHERE vendor_id = ?", (vendor_id,)).fetchone()
        return dict(row) if row else None


def get_vendor_by_name(name: str, db_path: Path = DB_PATH) -> Optional[dict[str, Any]]:
    with db_session(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM vendors WHERE LOWER(name) = LOWER(?)", (name,)
        ).fetchone()
        return dict(row) if row else None


def list_vendors(db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    with db_session(db_path) as conn:
        rows = conn.execute("SELECT * FROM vendors ORDER BY name").fetchall()
        return [dict(r) for r in rows]


def is_approved_vendor(name: str, db_path: Path = DB_PATH) -> bool:
    with db_session(db_path) as conn:
        row = conn.execute(
            "SELECT approved FROM vendors WHERE LOWER(name) = LOWER(?)", (name,)
        ).fetchone()
        return bool(row and row["approved"])


# ---------------------------------------------------------------------------
# Purchase order queries
# ---------------------------------------------------------------------------


def get_purchase_order(po_number: str, db_path: Path = DB_PATH) -> Optional[dict[str, Any]]:
    with db_session(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM purchase_orders WHERE po_number = ?", (po_number,)
        ).fetchone()
        return dict(row) if row else None


def list_purchase_orders(db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    with db_session(db_path) as conn:
        rows = conn.execute("SELECT * FROM purchase_orders ORDER BY issued_date DESC").fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Invoice CRUD
# ---------------------------------------------------------------------------


def upsert_invoice(invoice_data: dict[str, Any], db_path: Path = DB_PATH) -> None:
    with db_session(db_path) as conn:
        conn.execute(
            """INSERT INTO invoices
               (invoice_id, source_filename, document_type, vendor_name, vendor_id,
                invoice_number, invoice_date, due_date, po_number, currency,
                subtotal, tax, total, line_items_json, extraction_confidence,
                ocr_confidence, ocr_used, status, created_at, updated_at)
               VALUES
               (:invoice_id, :source_filename, :document_type, :vendor_name, :vendor_id,
                :invoice_number, :invoice_date, :due_date, :po_number, :currency,
                :subtotal, :tax, :total, :line_items_json, :extraction_confidence,
                :ocr_confidence, :ocr_used, :status, :created_at, :updated_at)
               ON CONFLICT(invoice_id) DO UPDATE SET
                 vendor_name=excluded.vendor_name,
                 vendor_id=excluded.vendor_id,
                 invoice_number=excluded.invoice_number,
                 invoice_date=excluded.invoice_date,
                 due_date=excluded.due_date,
                 po_number=excluded.po_number,
                 currency=excluded.currency,
                 subtotal=excluded.subtotal,
                 tax=excluded.tax,
                 total=excluded.total,
                 line_items_json=excluded.line_items_json,
                 extraction_confidence=excluded.extraction_confidence,
                 ocr_confidence=excluded.ocr_confidence,
                 ocr_used=excluded.ocr_used,
                 status=excluded.status,
                 updated_at=excluded.updated_at""",
            invoice_data,
        )


def get_invoice(invoice_id: str, db_path: Path = DB_PATH) -> Optional[dict[str, Any]]:
    with db_session(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM invoices WHERE invoice_id = ?", (invoice_id,)
        ).fetchone()
        return dict(row) if row else None


def list_invoices(
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db_path: Path = DB_PATH,
) -> list[dict[str, Any]]:
    with db_session(db_path) as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM invoices WHERE status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (status, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM invoices ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [dict(r) for r in rows]


def update_invoice_status(
    invoice_id: str, status: str, db_path: Path = DB_PATH
) -> None:
    with db_session(db_path) as conn:
        conn.execute(
            "UPDATE invoices SET status = ?, updated_at = ? WHERE invoice_id = ?",
            (status, datetime.utcnow().isoformat(), invoice_id),
        )


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


def append_audit_entry(entry: dict[str, Any], db_path: Path = DB_PATH) -> None:
    """Append an immutable audit entry. Never updates existing entries."""
    with db_session(db_path) as conn:
        conn.execute(
            """INSERT INTO audit_log
               (entry_id, invoice_id, event_type, actor, description,
                before_state, after_state, metadata, timestamp)
               VALUES
               (:entry_id, :invoice_id, :event_type, :actor, :description,
                :before_state, :after_state, :metadata, :timestamp)""",
            entry,
        )


def get_audit_trail(invoice_id: str, db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    with db_session(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log WHERE invoice_id = ? ORDER BY timestamp ASC",
            (invoice_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_full_audit_trail(
    limit: int = 500, db_path: Path = DB_PATH
) -> list[dict[str, Any]]:
    with db_session(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Governance and agent decisions
# ---------------------------------------------------------------------------


def save_governance_decision(decision: dict[str, Any], db_path: Path = DB_PATH) -> None:
    with db_session(db_path) as conn:
        conn.execute(
            """INSERT INTO governance_decisions
               (decision_id, invoice_id, rule_triggered, decision, escalation_level,
                reason, actor, threshold_value, actual_value, timestamp)
               VALUES
               (:decision_id, :invoice_id, :rule_triggered, :decision, :escalation_level,
                :reason, :actor, :threshold_value, :actual_value, :timestamp)""",
            decision,
        )


def save_agent_decision(decision: dict[str, Any], db_path: Path = DB_PATH) -> None:
    with db_session(db_path) as conn:
        conn.execute(
            """INSERT INTO agent_decisions
               (decision_id, invoice_id, agent_role, stage_input_summary,
                stage_output_summary, confidence, escalated, escalation_reason,
                processing_time_ms, timestamp)
               VALUES
               (:decision_id, :invoice_id, :agent_role, :stage_input_summary,
                :stage_output_summary, :confidence, :escalated, :escalation_reason,
                :processing_time_ms, :timestamp)""",
            decision,
        )


def get_governance_stats(db_path: Path = DB_PATH) -> dict[str, Any]:
    """Aggregate stats for the governance dashboard."""
    with db_session(db_path) as conn:
        total = conn.execute("SELECT COUNT(*) FROM invoices").fetchone()[0]
        pending = conn.execute(
            "SELECT COUNT(*) FROM invoices WHERE status IN ('pending','on_hold','flagged')"
        ).fetchone()[0]
        approved = conn.execute(
            "SELECT COUNT(*) FROM invoices WHERE status = 'approved'"
        ).fetchone()[0]
        l1 = conn.execute(
            "SELECT COUNT(*) FROM governance_decisions WHERE escalation_level = 'l1_manager'"
        ).fetchone()[0]
        l2 = conn.execute(
            "SELECT COUNT(*) FROM governance_decisions WHERE escalation_level = 'l2_controller'"
        ).fetchone()[0]
        l3 = conn.execute(
            "SELECT COUNT(*) FROM governance_decisions WHERE escalation_level = 'l3_vp_cfo'"
        ).fetchone()[0]
        blocked = conn.execute(
            "SELECT COUNT(*) FROM governance_decisions WHERE decision = 'block'"
        ).fetchone()[0]
        avg_conf = conn.execute(
            "SELECT AVG(confidence) FROM agent_decisions"
        ).fetchone()[0] or 0.0
        ocr_fail = conn.execute(
            "SELECT COUNT(*) FROM invoices WHERE ocr_confidence < 0.85"
        ).fetchone()[0]
        dupe = conn.execute(
            "SELECT COUNT(*) FROM governance_decisions WHERE rule_triggered = 'duplicate_detection'"
        ).fetchone()[0]
        unknown_v = conn.execute(
            "SELECT COUNT(*) FROM governance_decisions WHERE rule_triggered = 'unknown_vendor'"
        ).fetchone()[0]
        variance = conn.execute(
            "SELECT COUNT(*) FROM governance_decisions WHERE rule_triggered = 'variance_threshold'"
        ).fetchone()[0]

        return {
            "total_processed": total,
            "pending_review": pending,
            "auto_approved": approved,
            "escalated_l1": l1,
            "escalated_l2": l2,
            "escalated_l3": l3,
            "blocked": blocked,
            "avg_confidence": round(avg_conf, 3),
            "ocr_failures": ocr_fail,
            "duplicate_flags": dupe,
            "unknown_vendor_flags": unknown_v,
            "amount_variance_flags": variance,
        }


# ---------------------------------------------------------------------------
# Human decision governance
# ---------------------------------------------------------------------------

VALID_DECISIONS = {"approve", "adjust_and_approve", "reject", "escalate_further"}
VALID_RATIONALE_CATEGORIES = {
    "amount_within_variance",
    "vendor_confirmed_correction",
    "po_mismatch_resolved",
    "duplicate_confirmed_void",
    "anomaly_is_legitimate",
    "requires_senior_review",
    "policy_exception_granted",
    "other",
}


def save_human_decision(decision: dict[str, Any], db_path: Path = DB_PATH) -> None:
    """Save a structured human reviewer decision."""
    with db_session(db_path) as conn:
        conn.execute(
            """INSERT INTO human_decisions
               (decision_id, invoice_id, reviewer_id, reviewer_name, decision,
                rationale_category, rationale_text, original_flag, original_agent,
                consistency_score, resolution_time_hours, timestamp)
               VALUES
               (:decision_id, :invoice_id, :reviewer_id, :reviewer_name, :decision,
                :rationale_category, :rationale_text, :original_flag, :original_agent,
                :consistency_score, :resolution_time_hours, :timestamp)""",
            decision,
        )
        # Update decision patterns
        _update_decision_pattern(conn, decision["original_flag"], decision["decision"], decision.get("resolution_time_hours", 0))
        # Append to audit trail
        conn.execute(
            """INSERT INTO audit_log
               (entry_id, invoice_id, event_type, actor, description,
                before_state, after_state, metadata, timestamp)
               VALUES (?, ?, 'human_review', ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid4()),
                decision["invoice_id"],
                f"human:{decision['reviewer_id']}",
                f"Human reviewer {decision['reviewer_name']} decided: {decision['decision']}",
                "escalated",
                decision["decision"],
                json.dumps({
                    "rationale_category": decision["rationale_category"],
                    "rationale_text": decision.get("rationale_text", ""),
                    "consistency_score": decision.get("consistency_score", -1),
                }),
                decision.get("timestamp", datetime.utcnow().isoformat()),
            ),
        )


def _update_decision_pattern(
    conn: sqlite3.Connection, flag_type: str, decision: str, resolution_hours: float
) -> None:
    """Update aggregate decision patterns for consistency scoring."""
    existing = conn.execute(
        "SELECT * FROM decision_patterns WHERE flag_type = ?", (flag_type,)
    ).fetchone()

    if existing:
        total = existing["total_decisions"] + 1
        approve = existing["approve_count"] + (1 if decision == "approve" else 0)
        reject = existing["reject_count"] + (1 if decision == "reject" else 0)
        adjust = existing["adjust_count"] + (1 if decision == "adjust_and_approve" else 0)
        escalate = existing["escalate_count"] + (1 if decision == "escalate_further" else 0)
        avg_hours = (
            (existing["avg_resolution_hours"] * existing["total_decisions"] + resolution_hours) / total
        )
        conn.execute(
            """UPDATE decision_patterns
               SET total_decisions = ?, approve_count = ?, reject_count = ?,
                   adjust_count = ?, escalate_count = ?, avg_resolution_hours = ?,
                   last_updated = ?
               WHERE flag_type = ?""",
            (total, approve, reject, adjust, escalate, round(avg_hours, 2),
             datetime.utcnow().isoformat(), flag_type),
        )
    else:
        conn.execute(
            """INSERT INTO decision_patterns
               (pattern_id, flag_type, total_decisions, approve_count, reject_count,
                adjust_count, escalate_count, avg_resolution_hours, last_updated)
               VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid4()), flag_type,
                1 if decision == "approve" else 0,
                1 if decision == "reject" else 0,
                1 if decision == "adjust_and_approve" else 0,
                1 if decision == "escalate_further" else 0,
                resolution_hours,
                datetime.utcnow().isoformat(),
            ),
        )


def calculate_consistency_score(flag_type: str, decision: str, db_path: Path = DB_PATH) -> float:
    """Calculate how consistent a decision is with historical patterns.
    Returns a score between 0.0 (completely inconsistent) and 1.0 (fully aligned)."""
    with db_session(db_path) as conn:
        pattern = conn.execute(
            "SELECT * FROM decision_patterns WHERE flag_type = ?", (flag_type,)
        ).fetchone()

        if not pattern or pattern["total_decisions"] < 3:
            return -1.0  # Not enough data to score

        total = pattern["total_decisions"]
        if decision == "approve":
            return round(pattern["approve_count"] / total, 3)
        elif decision == "reject":
            return round(pattern["reject_count"] / total, 3)
        elif decision == "adjust_and_approve":
            return round(pattern["adjust_count"] / total, 3)
        elif decision == "escalate_further":
            return round(pattern["escalate_count"] / total, 3)
        return 0.0


def get_human_decisions(
    invoice_id: Optional[str] = None,
    reviewer_id: Optional[str] = None,
    limit: int = 50,
    db_path: Path = DB_PATH,
) -> list[dict[str, Any]]:
    """Retrieve human decisions with optional filters."""
    with db_session(db_path) as conn:
        if invoice_id:
            rows = conn.execute(
                "SELECT * FROM human_decisions WHERE invoice_id = ? ORDER BY timestamp DESC",
                (invoice_id,),
            ).fetchall()
        elif reviewer_id:
            rows = conn.execute(
                "SELECT * FROM human_decisions WHERE reviewer_id = ? ORDER BY timestamp DESC LIMIT ?",
                (reviewer_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM human_decisions ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]


def get_decision_patterns(db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    """Get all decision patterns for the consistency dashboard."""
    with db_session(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM decision_patterns ORDER BY total_decisions DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_reviewer_consistency(reviewer_id: str, db_path: Path = DB_PATH) -> dict[str, Any]:
    """Get consistency metrics for a specific reviewer."""
    with db_session(db_path) as conn:
        decisions = conn.execute(
            "SELECT * FROM human_decisions WHERE reviewer_id = ?", (reviewer_id,)
        ).fetchall()

        if not decisions:
            return {"reviewer_id": reviewer_id, "total_reviews": 0, "avg_consistency": -1}

        scores = [d["consistency_score"] for d in decisions if d["consistency_score"] >= 0]
        avg_score = round(sum(scores) / len(scores), 3) if scores else -1
        avg_time = round(
            sum(d["resolution_time_hours"] for d in decisions) / len(decisions), 2
        )

        return {
            "reviewer_id": reviewer_id,
            "total_reviews": len(decisions),
            "avg_consistency": avg_score,
            "avg_resolution_hours": avg_time,
            "decisions_breakdown": {
                "approve": sum(1 for d in decisions if d["decision"] == "approve"),
                "reject": sum(1 for d in decisions if d["decision"] == "reject"),
                "adjust": sum(1 for d in decisions if d["decision"] == "adjust_and_approve"),
                "escalate": sum(1 for d in decisions if d["decision"] == "escalate_further"),
            },
        }


def get_pending_reviews(db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    """Get invoices that are escalated and awaiting human review."""
    with db_session(db_path) as conn:
        rows = conn.execute(
            """SELECT i.*, gd.rule_triggered, gd.escalation_level, gd.reason as escalation_reason
               FROM invoices i
               JOIN governance_decisions gd ON i.invoice_id = gd.invoice_id
               WHERE i.status IN ('flagged', 'on_hold')
                 AND gd.escalation_level != 'none'
                 AND i.invoice_id NOT IN (SELECT invoice_id FROM human_decisions)
               ORDER BY gd.timestamp ASC""",
        ).fetchall()
        return [dict(r) for r in rows]


def check_duplicate_invoice(
    invoice_number: str,
    vendor_name: str,
    db_path: Path = DB_PATH,
    within_days: int = 90,
) -> Optional[dict[str, Any]]:
    """Check for a duplicate invoice within the lookback window."""
    with db_session(db_path) as conn:
        row = conn.execute(
            """SELECT * FROM invoices
               WHERE invoice_number = ?
                 AND LOWER(vendor_name) = LOWER(?)
                 AND julianday('now') - julianday(created_at) <= ?
               LIMIT 1""",
            (invoice_number, vendor_name, within_days),
        ).fetchone()
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------


def bootstrap(db_path: Path = DB_PATH) -> None:
    """Initialize schema and seed reference data."""
    init_db(db_path)
    seed_db(db_path)


if __name__ == "__main__":
    bootstrap()
    print(f"Database bootstrapped at {DB_PATH}")
    print(f"Vendors: {len(list_vendors())}")
    print(f"Purchase orders: {len(list_purchase_orders())}")
