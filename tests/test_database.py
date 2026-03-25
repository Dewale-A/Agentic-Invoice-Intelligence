"""
Tests for database functions in src/data/database.py
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from src.data.database import (
    append_audit_entry,
    check_duplicate_invoice,
    get_invoice,
    get_purchase_order,
    init_db,
    is_approved_vendor,
    list_invoices,
    list_purchase_orders,
    list_vendors,
    save_governance_decision,
    seed_db,
)


# ---------------------------------------------------------------------------
# Schema and seeding
# ---------------------------------------------------------------------------


class TestInit:
    def test_init_creates_tables(self, tmp_path):
        db = tmp_path / "test_init.db"
        init_db(db)
        import sqlite3
        conn = sqlite3.connect(str(db))
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        assert "vendors" in tables
        assert "purchase_orders" in tables
        assert "invoices" in tables
        assert "audit_log" in tables
        assert "governance_decisions" in tables

    def test_seed_populates_vendors(self, tmp_path):
        db = tmp_path / "seed.db"
        init_db(db)
        seed_db(db)
        vendors = list_vendors(db)
        assert len(vendors) >= 5

    def test_seed_populates_purchase_orders(self, tmp_path):
        db = tmp_path / "seed_po.db"
        init_db(db)
        seed_db(db)
        pos = list_purchase_orders(db)
        assert len(pos) >= 5


# ---------------------------------------------------------------------------
# Vendor queries
# ---------------------------------------------------------------------------


class TestVendors:
    def test_approved_vendor_recognised(self, _fresh_db):
        # Seeded vendors include "Acme Cloud Services"
        assert is_approved_vendor("Acme Cloud Services", _fresh_db) is True

    def test_unknown_vendor_not_approved(self, _fresh_db):
        assert is_approved_vendor("ShadowTech Solutions Inc.", _fresh_db) is False

    def test_list_vendors_returns_records(self, _fresh_db):
        vendors = list_vendors(_fresh_db)
        assert isinstance(vendors, list)
        assert len(vendors) > 0


# ---------------------------------------------------------------------------
# Purchase order queries
# ---------------------------------------------------------------------------


class TestPurchaseOrders:
    def test_get_known_po(self, _fresh_db):
        po = get_purchase_order("PO-2024-001", _fresh_db)
        assert po is not None
        assert "amount" in po

    def test_get_unknown_po_returns_none(self, _fresh_db):
        po = get_purchase_order("PO-DOES-NOT-EXIST", _fresh_db)
        assert po is None

    def test_list_purchase_orders(self, _fresh_db):
        pos = list_purchase_orders(_fresh_db)
        assert len(pos) >= 1


# ---------------------------------------------------------------------------
# Invoice CRUD
# ---------------------------------------------------------------------------


class TestInvoices:
    def _insert_invoice(self, db, invoice_number="INV-DB-001", vendor_name="Acme Cloud Services"):
        import sqlite3
        conn = sqlite3.connect(str(db))
        invoice_id = str(uuid4())
        conn.execute(
            """INSERT INTO invoices
               (invoice_id, source_filename, status, invoice_number, vendor_name,
                total, extraction_confidence, ocr_confidence, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                invoice_id,
                "test.pdf",
                "pending",
                invoice_number,
                vendor_name,
                1000.0,
                0.95,
                1.0,
                datetime.utcnow().isoformat(),
                datetime.utcnow().isoformat(),
            ),
        )
        conn.commit()
        conn.close()
        return invoice_id

    def test_get_invoice(self, _fresh_db):
        inv_id = self._insert_invoice(_fresh_db)
        inv = get_invoice(inv_id, _fresh_db)
        assert inv is not None
        assert inv["invoice_id"] == inv_id

    def test_get_invoice_not_found(self, _fresh_db):
        inv = get_invoice(str(uuid4()), _fresh_db)
        assert inv is None

    def test_list_invoices(self, _fresh_db):
        self._insert_invoice(_fresh_db, "INV-LIST-001")
        self._insert_invoice(_fresh_db, "INV-LIST-002")
        invoices = list_invoices(db_path=_fresh_db)
        assert len(invoices) >= 2

    def test_check_duplicate_invoice_found(self, _fresh_db):
        self._insert_invoice(_fresh_db, "INV-DUP-001", "Acme Cloud Services")
        result = check_duplicate_invoice("INV-DUP-001", "Acme Cloud Services", db_path=_fresh_db, within_days=90)
        assert result is not None

    def test_check_duplicate_invoice_not_found(self, _fresh_db):
        result = check_duplicate_invoice("DOES-NOT-EXIST", "Vendor X", db_path=_fresh_db, within_days=90)
        assert result is None


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


class TestAuditLog:
    def test_append_audit_entry(self, _fresh_db):
        entry = {
            "entry_id": str(uuid4()),
            "invoice_id": str(uuid4()),
            "event_type": "test.event",
            "actor": "test_agent",
            "description": "Test audit entry",
            "before_state": None,
            "after_state": None,
            "metadata": "{}",
            "timestamp": datetime.utcnow().isoformat(),
        }
        append_audit_entry(entry, _fresh_db)

        import sqlite3
        conn = sqlite3.connect(str(_fresh_db))
        row = conn.execute(
            "SELECT * FROM audit_log WHERE entry_id=?", (entry["entry_id"],)
        ).fetchone()
        conn.close()
        assert row is not None


# ---------------------------------------------------------------------------
# Governance decisions
# ---------------------------------------------------------------------------


class TestGovernanceDecisions:
    def test_save_governance_decision(self, _fresh_db):
        decision = {
            "decision_id": str(uuid4()),
            "invoice_id": str(uuid4()),
            "rule_triggered": "test_rule",
            "decision": "escalate",
            "escalation_level": "human_review",
            "reason": "Unit test",
            "actor": "validation_officer",
            "threshold_value": 0.85,
            "actual_value": 0.60,
            "timestamp": datetime.utcnow().isoformat(),
        }
        save_governance_decision(decision, _fresh_db)

        import sqlite3
        conn = sqlite3.connect(str(_fresh_db))
        row = conn.execute(
            "SELECT * FROM governance_decisions WHERE decision_id=?",
            (decision["decision_id"],),
        ).fetchone()
        conn.close()
        assert row is not None
