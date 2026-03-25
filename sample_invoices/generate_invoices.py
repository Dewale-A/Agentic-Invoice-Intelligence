"""
Generate 10 realistic sample PDF invoices using reportlab.

Each invoice tests a different scenario in the pipeline:
  INV-001: Clean digital invoice, all fields present, matches PO exactly.
  INV-002: Clean digital invoice, matches PO with minor rounding variance.
  INV-003: ANOMALY - Amount exceeds PO by 35% (triggers variance gate).
  INV-004: ANOMALY - Unknown/unapproved vendor (triggers vendor hold).
  INV-005: ANOMALY - Future-dated invoice (triggers date anomaly).
  INV-006: ANOMALY - Low OCR confidence (simulated via messy layout).
  INV-007: ANOMALY - Duplicate of INV-001 (same invoice# + vendor).
  INV-008: Clean high-value invoice >$25K (triggers L2 materiality gate).
  INV-009: Clean very high-value invoice >$100K (triggers L3 materiality gate).
  INV-010: Invoice missing multiple fields (triggers missing fields anomaly).

Run: python sample_invoices/generate_invoices.py
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False
    print("reportlab not installed. Install with: pip install reportlab")
    exit(1)


def _header_table(vendor_name: str, vendor_addr: str, invoice_no: str,
                  invoice_date: str, due_date: str, po_number: str = "") -> Table:
    styles = getSampleStyleSheet()
    data = [
        [Paragraph(f"<b>{vendor_name}</b>", styles["Normal"]),
         Paragraph(f"<b>INVOICE</b>", styles["Heading2"])],
        [Paragraph(vendor_addr, styles["Normal"]),
         Paragraph(f"Invoice #: {invoice_no}", styles["Normal"])],
        ["",
         Paragraph(f"Invoice Date: {invoice_date}", styles["Normal"])],
        ["",
         Paragraph(f"Due Date: {due_date}", styles["Normal"])],
    ]
    if po_number:
        data.append(["", Paragraph(f"PO Number: {po_number}", styles["Normal"])])

    t = Table(data, colWidths=[4 * inch, 3 * inch])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def _line_items_table(items: list[dict]) -> Table:
    header = ["Description", "Qty", "Unit Price", "Total"]
    rows = [header]
    for item in items:
        rows.append([
            item["description"],
            str(item["qty"]),
            f"${item['unit_price']:,.2f}",
            f"${item['total']:,.2f}",
        ])
    t = Table(rows, colWidths=[3.5 * inch, 0.75 * inch, 1.25 * inch, 1.25 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2C3E50")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8F9FA")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#DEE2E6")),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _totals_table(subtotal: float, tax: float, total: float) -> Table:
    data = [
        ["", "Subtotal:", f"${subtotal:,.2f}"],
        ["", "Tax (13% HST):", f"${tax:,.2f}"],
        ["", "TOTAL DUE:", f"${total:,.2f}"],
    ]
    t = Table(data, colWidths=[3.5 * inch, 1.75 * inch, 1.5 * inch])
    t.setStyle(TableStyle([
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("LINEABOVE", (1, 2), (-1, 2), 1, colors.black),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def _build_invoice(
    filename: str,
    vendor_name: str,
    vendor_addr: str,
    invoice_no: str,
    invoice_date: str,
    due_date: str,
    po_number: str,
    items: list[dict],
    subtotal: float,
    tax: float,
    total: float,
    currency: str = "USD",
    bill_to: str = "Accounts Payable\n123 Corporate Drive\nCalgary, AB T2P 1J9",
    extra_notes: str = "",
) -> None:
    styles = getSampleStyleSheet()
    filepath = OUTPUT_DIR / filename
    doc = SimpleDocTemplate(str(filepath), pagesize=letter,
                            leftMargin=0.75 * inch, rightMargin=0.75 * inch,
                            topMargin=0.75 * inch, bottomMargin=0.75 * inch)

    elements = []

    # Header
    elements.append(_header_table(vendor_name, vendor_addr, invoice_no,
                                   invoice_date, due_date, po_number))
    elements.append(Spacer(1, 0.2 * inch))

    # Bill To
    elements.append(Paragraph("<b>Bill To:</b>", styles["Normal"]))
    elements.append(Paragraph(bill_to.replace("\n", "<br/>"), styles["Normal"]))
    elements.append(Spacer(1, 0.2 * inch))

    # Line items
    elements.append(_line_items_table(items))
    elements.append(Spacer(1, 0.1 * inch))

    # Totals
    elements.append(_totals_table(subtotal, tax, total))
    elements.append(Spacer(1, 0.2 * inch))

    # Currency
    elements.append(Paragraph(f"Currency: {currency}", styles["Normal"]))

    if extra_notes:
        elements.append(Spacer(1, 0.15 * inch))
        elements.append(Paragraph(f"<i>{extra_notes}</i>", styles["Normal"]))

    elements.append(Spacer(1, 0.3 * inch))
    elements.append(Paragraph(
        "Thank you for your business. Please remit payment to the bank account on file.",
        styles["Normal"]
    ))

    doc.build(elements)
    print(f"  Generated: {filename}")


def generate_all() -> None:
    today = date.today()
    fmt = lambda d: d.strftime("%B %d, %Y")

    print("Generating sample invoices...")

    # INV-001: Clean, all fields, matches PO-2024-001 ($15,000)
    _build_invoice(
        "INV-001-acme-cloud.pdf",
        "Acme Cloud Services", "100 Tech Blvd, San Francisco, CA 94105",
        "INV-2024-0101", fmt(today - timedelta(days=5)), fmt(today + timedelta(days=25)),
        "PO-2024-001",
        [{"description": "Cloud Infrastructure Q1 - Compute", "qty": 1, "unit_price": 8000.00, "total": 8000.00},
         {"description": "Cloud Infrastructure Q1 - Storage", "qty": 1, "unit_price": 4000.00, "total": 4000.00},
         {"description": "Cloud Infrastructure Q1 - Bandwidth", "qty": 1, "unit_price": 1770.80, "total": 1770.80}],
        13770.80, 1229.20, 15000.00,
    )

    # INV-002: Clean, minor rounding, matches PO-2024-007 ($3,500)
    _build_invoice(
        "INV-002-greenleaf.pdf",
        "GreenLeaf Facilities", "55 Green St, Toronto, ON M5V 2H1",
        "INV-GL-0234", fmt(today - timedelta(days=3)), fmt(today + timedelta(days=27)),
        "PO-2024-007",
        [{"description": "Office Cleaning - March 2024", "qty": 4, "unit_price": 700.00, "total": 2800.00},
         {"description": "Maintenance Services - March 2024", "qty": 1, "unit_price": 398.23, "total": 398.23}],
        3198.23, 293.77, 3492.00,
        extra_notes="Amount reflects a minor rounding adjustment to invoice total.",
    )

    # INV-003: ANOMALY - amount 35% above PO-2024-005 ($12,000 -> billed $16,200)
    _build_invoice(
        "INV-003-eagleeye-variance.pdf",
        "EagleEye Security", "200 Security Ave, Austin, TX 78701",
        "INV-EE-9021", fmt(today - timedelta(days=10)), fmt(today + timedelta(days=20)),
        "PO-2024-005",
        [{"description": "Penetration Testing Phase 1", "qty": 1, "unit_price": 8000.00, "total": 8000.00},
         {"description": "Penetration Testing Phase 2 (Extended)", "qty": 1, "unit_price": 6000.00, "total": 6000.00},
         {"description": "Security Audit Report", "qty": 1, "unit_price": 354.87, "total": 354.87}],
        14354.87, 1845.13, 16200.00,
        extra_notes="Extended scope per verbal change order approval.",
    )

    # INV-004: ANOMALY - Unknown vendor not in registry
    _build_invoice(
        "INV-004-unknown-vendor.pdf",
        "ShadowTech Solutions Inc.", "Unknown Address, Unknown City",
        "ST-INV-0055", fmt(today - timedelta(days=2)), fmt(today + timedelta(days=28)),
        "PO-2024-999",
        [{"description": "IT Consulting Services", "qty": 40, "unit_price": 150.00, "total": 6000.00},
         {"description": "Software Licensing", "qty": 1, "unit_price": 2000.00, "total": 2000.00}],
        8000.00, 1040.00, 9040.00,
        extra_notes="This vendor is not registered in the approved vendor registry.",
    )

    # INV-005: ANOMALY - Future dated (30 days in the future)
    _build_invoice(
        "INV-005-future-dated.pdf",
        "BrightPath Consulting", "Suite 400, 1000 Bay St, Toronto, ON M5S 3A3",
        "BP-2024-0077", fmt(today + timedelta(days=30)), fmt(today + timedelta(days=60)),
        "PO-2024-002",
        [{"description": "Digital Transformation Advisory - Month 1", "qty": 1, "unit_price": 12000.00, "total": 12000.00},
         {"description": "Project Management Office Setup", "qty": 1, "unit_price": 8000.00, "total": 8000.00},
         {"description": "Stakeholder Workshop Facilitation", "qty": 2, "unit_price": 2500.00, "total": 5000.00}],
        22123.89, 1876.11, 24000.00,
        extra_notes="NOTE: This invoice is dated in the future - this is an anomaly test case.",
    )

    # INV-006: Low OCR confidence - simulate with dense/noisy layout
    _build_invoice(
        "INV-006-low-quality.pdf",
        "CoreNet Networking", "7F 99 Network Way, Vancouver, BC V6B 1A1",
        "CN20240189", fmt(today - timedelta(days=15)), fmt(today + timedelta(days=15)),
        "PO-2024-003",
        [{"description": "Network Switch Installation x4", "qty": 4, "unit_price": 1200.00, "total": 4800.00},
         {"description": "Cable Management and Labeling", "qty": 1, "unit_price": 800.00, "total": 800.00},
         {"description": "Site Survey and Documentation", "qty": 1, "unit_price": 600.00, "total": 600.00}],
        6371.68, 628.32, 7000.00,
        extra_notes="This invoice simulates a low-quality scan scenario.",
    )

    # INV-007: ANOMALY - Duplicate of INV-001 (same invoice# INV-2024-0101, same vendor)
    _build_invoice(
        "INV-007-duplicate.pdf",
        "Acme Cloud Services", "100 Tech Blvd, San Francisco, CA 94105",
        "INV-2024-0101",  # Same number as INV-001
        fmt(today - timedelta(days=1)), fmt(today + timedelta(days=29)),
        "PO-2024-001",
        [{"description": "Cloud Infrastructure Q1 - Compute", "qty": 1, "unit_price": 8000.00, "total": 8000.00},
         {"description": "Cloud Infrastructure Q1 - Storage", "qty": 1, "unit_price": 4000.00, "total": 4000.00},
         {"description": "Cloud Infrastructure Q1 - Bandwidth", "qty": 1, "unit_price": 1770.80, "total": 1770.80}],
        13770.80, 1229.20, 15000.00,
        extra_notes="DUPLICATE SUBMISSION - same invoice number as previously submitted.",
    )

    # INV-008: High value >$25K triggers L2 Controller (PO-2024-002, $25K)
    _build_invoice(
        "INV-008-high-value-l2.pdf",
        "BrightPath Consulting", "Suite 400, 1000 Bay St, Toronto, ON M5S 3A3",
        "BP-2024-0088", fmt(today - timedelta(days=7)), fmt(today + timedelta(days=38)),
        "PO-2024-002",
        [{"description": "Digital Transformation - Phase 1 Deliverable", "qty": 1, "unit_price": 15000.00, "total": 15000.00},
         {"description": "Executive Stakeholder Reporting", "qty": 1, "unit_price": 5000.00, "total": 5000.00},
         {"description": "Change Management Framework", "qty": 1, "unit_price": 3097.35, "total": 3097.35}],
        22210.92, 2789.08, 25000.00,
        extra_notes="High-value invoice requiring L2 Controller approval (>$25,000).",
    )

    # INV-009: Very high value >$100K triggers L3 VP/CFO (PO-2024-013, $45K -> using NexGen $45K PO)
    # Using PO-2024-013 at $45K but billing slightly below for a clean match scenario
    _build_invoice(
        "INV-009-very-high-value-l3.pdf",
        "NexGen Software", "One Innovation Dr, Seattle, WA 98101",
        "NXG-2024-0001", fmt(today - timedelta(days=14)), fmt(today + timedelta(days=16)),
        "PO-2024-013",
        [{"description": "ERP Integration Middleware - Annual License", "qty": 1, "unit_price": 35000.00, "total": 35000.00},
         {"description": "Implementation Services", "qty": 50, "unit_price": 200.00, "total": 10000.00},
         {"description": "Training and Onboarding Package", "qty": 1, "unit_price": 55752.21, "total": 55752.21}],
        88252.21, 11747.79, 100000.00,
        extra_notes="High-value contract requiring L3 VP/CFO approval (>$100,000).",
    )

    # INV-010: Missing multiple required fields
    _build_invoice(
        "INV-010-missing-fields.pdf",
        "HighTower Analytics", "Analytics Tower, 500 Data St, Chicago, IL 60601",
        "",  # Missing invoice number
        "",  # Missing date
        fmt(today + timedelta(days=30)),
        "",  # Missing PO
        [{"description": "Analytics Platform Setup", "qty": 1, "unit_price": 9000.00, "total": 9000.00}],
        7964.60, 1035.40, 9000.00,
        extra_notes="INCOMPLETE INVOICE: Missing invoice number, date, and PO reference.",
    )

    print(f"\nAll 10 sample invoices generated in {OUTPUT_DIR}/")


if __name__ == "__main__":
    generate_all()
