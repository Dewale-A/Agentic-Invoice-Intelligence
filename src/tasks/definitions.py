"""
Task definitions for the AgenticInvoiceIntelligence pipeline.

Design decision: tasks are parameterized by a batch context dict rather than
hard-coded. This enables the same task definitions to be reused across different
invoice batches without creating new Task objects for each run.

Each task corresponds to one agent stage and produces a clearly typed output
that feeds the next stage. The expected_output field is used by CrewAI for
task chaining and output validation.
"""

from __future__ import annotations

from typing import Any

from crewai import Agent, Task


def create_document_intake_task(
    agent: Agent,
    batch_context: dict[str, Any],
) -> Task:
    """
    Task 1: Process incoming invoice documents.

    Input: file paths from batch_context['file_paths']
    Output: List of {filename, raw_text, document_type, ocr_used, ocr_confidence}
    """
    file_paths = batch_context.get("file_paths", [])
    file_list = "\n".join(f"  - {fp}" for fp in file_paths)

    return Task(
        description=(
            f"Process the following invoice document(s) for the batch '{batch_context.get('batch_id', 'N/A')}':\n"
            f"{file_list}\n\n"
            "For each document:\n"
            "1. Extract all text using pdfplumber. If the PDF has no text layer, use pytesseract OCR.\n"
            "2. Classify the document type (invoice, receipt, purchase_order, statement).\n"
            "3. Record the OCR confidence score (1.0 for digital PDFs, tesseract confidence for OCR).\n"
            "4. Return a structured result for each file including: filename, document_type, "
            "raw_text (first 500 chars for summary), ocr_used (bool), ocr_confidence (0.0-1.0).\n\n"
            "Flag any document where OCR confidence is below 0.85 as requiring human verification."
        ),
        expected_output=(
            "A JSON array where each element represents a processed document with fields: "
            "filename, document_type, raw_text_preview, ocr_used, ocr_confidence, "
            "classification_confidence. Include a summary line noting how many documents "
            "were processed and how many triggered the OCR confidence gate."
        ),
        agent=agent,
    )


def create_data_extraction_task(
    agent: Agent,
    batch_context: dict[str, Any],
    context_tasks: list[Task] | None = None,
) -> Task:
    """
    Task 2: Extract structured data from raw invoice text.

    Consumes output from the document intake task.
    Output: List of ExtractedInvoice-compatible JSON objects.
    """
    return Task(
        description=(
            "Using the document intake results from the previous stage, extract structured "
            "invoice data from each document. For each invoice:\n\n"
            "1. Parse: vendor_name, invoice_number, invoice_date, due_date, po_number, "
            "currency, subtotal, tax, total.\n"
            "2. Extract line items where available: description, quantity, unit_price, total.\n"
            "3. Assign an extraction_confidence score (0.0-1.0) reflecting the proportion of "
            "required fields successfully extracted and the quality of the extraction.\n"
            "4. Flag any invoice where extraction_confidence is below 0.70 for human review.\n\n"
            "Use pattern matching first, then apply reasoning to fill gaps. "
            "Never fabricate values: use null for fields that cannot be determined."
        ),
        expected_output=(
            "A JSON array of extracted invoice objects. Each object must include: "
            "source_filename, vendor_name, invoice_number, invoice_date, due_date, "
            "po_number, currency, subtotal, tax, total, line_items, extraction_confidence. "
            "Include a processing summary noting the average confidence score and any "
            "invoices flagged for low confidence."
        ),
        agent=agent,
        context=context_tasks or [],
    )


def create_validation_task(
    agent: Agent,
    batch_context: dict[str, Any],
    context_tasks: list[Task] | None = None,
) -> Task:
    """
    Task 3: Validate extracted invoice data against reference systems.
    """
    return Task(
        description=(
            "Validate each extracted invoice against the reference data systems. For each invoice:\n\n"
            "1. VENDOR CHECK: Verify vendor_name exists in the approved vendor registry.\n"
            "2. PO CHECK: Verify po_number exists and the invoice total is within 10% of the PO amount.\n"
            "3. DATE CHECK: Confirm invoice_date is not in the future (more than 7 days).\n"
            "4. ARITHMETIC CHECK: Verify subtotal + tax = total (within $1 tolerance).\n"
            "5. CURRENCY CHECK: Confirm currency is an accepted ISO code.\n\n"
            "For each check, report: status (pass/fail/warning/skipped), extracted_value, "
            "expected_value, message, and confidence. Aggregate into an overall validation status. "
            "Compute a validation_confidence score as the mean of individual field confidences."
        ),
        expected_output=(
            "A JSON array of ValidationReport objects. Each report includes: invoice_id, "
            "overall_status, field_results (array of per-field results), po_match (bool), "
            "po_variance_pct, vendor_approved (bool), validation_confidence. "
            "Include a batch summary: total passed, failed, warnings."
        ),
        agent=agent,
        context=context_tasks or [],
    )


def create_anomaly_detection_task(
    agent: Agent,
    batch_context: dict[str, Any],
    context_tasks: list[Task] | None = None,
) -> Task:
    """
    Task 4: Detect anomalies and fraud indicators.
    """
    return Task(
        description=(
            "Analyze each invoice for anomalies, irregularities, and fraud indicators. "
            "Run the following checks for each invoice:\n\n"
            "1. DUPLICATE CHECK: Same invoice_number + vendor_name within 90 days. Severity: CRITICAL.\n"
            "2. AMOUNT OUTLIER: Invoice total deviates from PO amount by more than 10%. "
            "Severity scales with deviation size (LOW < 15%, MEDIUM < 30%, HIGH < 50%, CRITICAL >= 50%).\n"
            "3. UNKNOWN VENDOR: Vendor not in approved registry. Severity: HIGH.\n"
            "4. DATE ANOMALY: Future-dated invoice (HIGH) or stale invoice >180 days (MEDIUM).\n"
            "5. ROUND NUMBER: Total is a suspiciously round number above $1000. Severity: LOW.\n"
            "6. MISSING FIELDS: Critical fields absent. Severity: HIGH if 2+ fields missing.\n\n"
            "For each anomaly, provide: anomaly_type, severity, description, evidence dict. "
            "Compute an overall risk_score (0.0-1.0)."
        ),
        expected_output=(
            "A JSON array of AnomalyReport objects. Each report includes: invoice_id, anomalies "
            "(array of AnomalyFlag objects), is_duplicate, amount_outlier, unknown_vendor, "
            "date_anomaly, overall_risk_score. Include a batch summary: total anomalies by severity."
        ),
        agent=agent,
        context=context_tasks or [],
    )


def create_reconciliation_task(
    agent: Agent,
    batch_context: dict[str, Any],
    context_tasks: list[Task] | None = None,
) -> Task:
    """
    Task 5: Generate the final reconciliation report.
    """
    return Task(
        description=(
            "Produce a comprehensive reconciliation report for the entire batch, incorporating "
            "results from all previous pipeline stages.\n\n"
            "1. MATCHED INVOICES: Invoices that passed all validations with no anomalies or only "
            "LOW severity anomalies. These are cleared for payment.\n"
            "2. FLAGGED ITEMS: Invoices with validation warnings or MEDIUM/HIGH anomalies. "
            "These require supervisor review.\n"
            "3. BLOCKED INVOICES: Invoices with CRITICAL anomalies (duplicates) or governance "
            "blocks. These must not be paid until cleared by human review.\n"
            "4. ESCALATION ROUTING: For each flagged/blocked invoice, specify the required "
            "approval level: L1 Manager (>$5K), L2 Controller (>$25K), L3 VP/CFO (>$100K).\n"
            "5. AUDIT TRAIL: Summarize all governance decisions made during processing.\n\n"
            "Compute batch totals: total_invoices, matched, flagged, blocked, total_value, "
            "flagged_value."
        ),
        expected_output=(
            "A comprehensive ReconciliationReport JSON object with: report_id, batch_id, "
            "generated_at, total_invoices, matched, flagged, approved, rejected, on_hold, "
            "total_value, flagged_value, items (full list), exceptions (flagged/blocked only), "
            "and an audit_trail summary. The report should be ready for controller review."
        ),
        agent=agent,
        context=context_tasks or [],
    )


def create_pipeline_tasks(
    agents: dict[str, Any],
    batch_context: dict[str, Any],
) -> list[Task]:
    """
    Create all pipeline tasks in sequential order with proper context chaining.

    Returns the task list ready for Crew execution.
    """
    t1 = create_document_intake_task(agents["document_intake"], batch_context)
    t2 = create_data_extraction_task(agents["data_extraction"], batch_context, context_tasks=[t1])
    t3 = create_validation_task(agents["validation"], batch_context, context_tasks=[t1, t2])
    t4 = create_anomaly_detection_task(agents["anomaly_detection"], batch_context, context_tasks=[t1, t2, t3])
    t5 = create_reconciliation_task(agents["reconciliation"], batch_context, context_tasks=[t1, t2, t3, t4])
    return [t1, t2, t3, t4, t5]
