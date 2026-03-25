"""Tests for FastAPI endpoints."""

from datetime import datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from run_server import create_app
from src.data.database import upsert_invoice


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


@pytest.fixture
def seeded_invoice():
    inv_id = str(uuid4())
    upsert_invoice({
        "invoice_id": inv_id,
        "source_filename": "api_test.pdf",
        "document_type": "invoice",
        "vendor_name": "Acme Cloud Services",
        "vendor_id": "VND001",
        "invoice_number": "API-001",
        "invoice_date": "2024-03-01",
        "due_date": "2024-03-31",
        "po_number": "PO-2024-001",
        "currency": "USD",
        "subtotal": 13274.34,
        "tax": 1725.66,
        "total": 15000.0,
        "line_items_json": "[]",
        "extraction_confidence": 0.95,
        "ocr_confidence": 1.0,
        "ocr_used": 0,
        "status": "validated",
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    })
    return inv_id


class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["vendor_count"] == 20


class TestVendorEndpoints:
    def test_list_vendors(self, client):
        resp = client.get("/vendors")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 20

    def test_list_purchase_orders(self, client):
        resp = client.get("/purchase-orders")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 15


class TestInvoiceList:
    def test_list_invoices_empty(self, client):
        resp = client.get("/invoices")
        assert resp.status_code == 200
        assert "invoices" in resp.json()


class TestInvoiceUpload:
    def test_upload_non_pdf_rejected(self, client):
        import io
        resp = client.post(
            "/invoices/upload",
            files={"file": ("test.txt", io.BytesIO(b"hello"), "text/plain")},
        )
        assert resp.status_code == 400


class TestInvoiceActions:
    def test_get_invoice(self, client, seeded_invoice):
        resp = client.get(f"/invoices/{seeded_invoice}")
        assert resp.status_code == 200
        assert resp.json()["invoice_number"] == "API-001"

    def test_get_invoice_not_found(self, client):
        resp = client.get(f"/invoices/{uuid4()}")
        assert resp.status_code == 404

    def test_approve_invoice(self, client, seeded_invoice):
        resp = client.post(
            f"/invoices/{seeded_invoice}/approve",
            json={"approved_by": "test_user", "notes": "Looks good"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"

    def test_reject_invoice(self, client, seeded_invoice):
        resp = client.post(
            f"/invoices/{seeded_invoice}/reject",
            json={"rejected_by": "test_user", "reason": "Fraudulent"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"

    def test_get_invoice_audit(self, client, seeded_invoice):
        resp = client.get(f"/invoices/{seeded_invoice}/audit")
        assert resp.status_code == 200
        assert "audit_trail" in resp.json()


class TestGovernanceEndpoints:
    def test_dashboard(self, client):
        resp = client.get("/governance/dashboard")
        assert resp.status_code == 200
        assert "total_processed" in resp.json()

    def test_audit_trail(self, client):
        resp = client.get("/governance/audit-trail")
        assert resp.status_code == 200


class TestReconciliation:
    def test_report(self, client):
        resp = client.get("/reconciliation/report")
        assert resp.status_code == 200

    def test_exceptions(self, client):
        resp = client.get("/reconciliation/exceptions")
        assert resp.status_code == 200
