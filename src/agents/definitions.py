"""
Agent definitions for the AgenticInvoiceIntelligence pipeline.

Design decision: each agent has a tightly scoped role aligned with a single
pipeline stage. This separation of concerns ensures that agents do not
cross-contaminate their outputs and that governance gates can be applied
cleanly between stages.

All agents use GPT-4o-mini as the default LLM to balance cost and quality
for invoice processing tasks. The model can be overridden via environment
variables for production deployments.
"""

from __future__ import annotations

import os

from crewai import Agent, LLM

# ---------------------------------------------------------------------------
# LLM configuration
# ---------------------------------------------------------------------------

_LLM_MODEL = os.getenv("AGENT_LLM_MODEL", "gpt-4o-mini")
_LLM_TEMPERATURE = float(os.getenv("AGENT_LLM_TEMPERATURE", "0.1"))
_LLM_MAX_TOKENS = int(os.getenv("AGENT_LLM_MAX_TOKENS", "2000"))

# Low temperature (0.1) is intentional: invoice processing requires
# deterministic extraction, not creative generation.
_DEFAULT_LLM = LLM(
    model=_LLM_MODEL,
    temperature=_LLM_TEMPERATURE,
    max_tokens=_LLM_MAX_TOKENS,
)


# ---------------------------------------------------------------------------
# Agent definitions
# ---------------------------------------------------------------------------


def create_document_intake_agent() -> Agent:
    """
    Agent 1: Document Intake Specialist

    Responsible for accepting PDF documents, classifying their type, and
    extracting raw text via pdfplumber with pytesseract OCR as a fallback.
    Outputs: document_type, raw_text, ocr_confidence_score.
    """
    return Agent(
        role="Document Intake Specialist",
        goal=(
            "Accept and process incoming PDF documents. Classify each document as invoice, "
            "receipt, purchase order, or statement. Extract all readable text using the best "
            "available method, whether direct PDF text extraction or OCR. Report an accurate "
            "OCR confidence score to enable downstream governance gating."
        ),
        backstory=(
            "You are a meticulous document processing specialist with deep expertise in "
            "financial document handling across enterprise environments. You have processed "
            "hundreds of thousands of invoices from diverse vendors, ranging from clean "
            "digital PDFs to poorly scanned paper documents. You understand that the quality "
            "of text extraction directly determines the accuracy of all downstream processing, "
            "so you apply rigorous quality controls and always report your confidence honestly. "
            "You never pass a low-quality extraction downstream without flagging it."
        ),
        llm=_DEFAULT_LLM,
        verbose=True,
        allow_delegation=False,
        max_iter=3,
    )


def create_data_extraction_agent() -> Agent:
    """
    Agent 2: Data Extraction Analyst

    Responsible for mapping raw text to the structured ExtractedInvoice schema.
    Uses a combination of regex heuristics and LLM reasoning to extract:
    vendor_name, invoice_number, date, line_items, total, tax, currency,
    po_number, and extraction_confidence.
    """
    return Agent(
        role="Data Extraction Analyst",
        goal=(
            "Transform raw invoice text into a structured, validated data schema. "
            "Extract all key fields: vendor name, invoice number, date, line items, "
            "totals, tax, currency, and PO number. Assign an honest extraction confidence "
            "score reflecting how complete and reliable the extraction is."
        ),
        backstory=(
            "You are an expert data analyst specializing in financial document parsing. "
            "You have an encyclopedic knowledge of invoice formats across industries and "
            "geographies. You approach every extraction as a structured problem: first "
            "applying deterministic pattern matching, then using your reasoning to fill "
            "gaps where patterns fail. You are scrupulously honest about confidence levels "
            "and would rather flag uncertainty than produce a confident but wrong extraction. "
            "You understand that downstream payment decisions depend on your accuracy."
        ),
        llm=_DEFAULT_LLM,
        verbose=True,
        allow_delegation=False,
        max_iter=3,
    )


def create_validation_agent() -> Agent:
    """
    Agent 3: Validation Officer

    Responsible for cross-referencing extracted invoice data against:
    - The approved vendor registry
    - Existing purchase orders and their amounts
    - Budget thresholds for the relevant cost center

    Outputs a field-level validation report with status per field.
    """
    return Agent(
        role="Validation Officer",
        goal=(
            "Cross-reference all extracted invoice fields against authoritative reference data. "
            "Validate vendor approval status, PO existence and amount alignment, date validity, "
            "and arithmetic consistency. Produce a field-level validation report with a clear "
            "status (pass/fail/warning) and confidence score for each field."
        ),
        backstory=(
            "You are a rigorous financial controls officer with a background in accounts payable "
            "and internal audit. You have seen every type of invoice fraud and billing error, "
            "which is why you never skip a validation step. You treat every discrepancy as "
            "significant until proven otherwise. You are methodical, document everything, and "
            "your validation reports are used directly in audit trails. You understand that "
            "a missed validation can mean an incorrect payment or a compliance finding."
        ),
        llm=_DEFAULT_LLM,
        verbose=True,
        allow_delegation=False,
        max_iter=3,
    )


def create_anomaly_detection_agent() -> Agent:
    """
    Agent 4: Anomaly Detection Specialist

    Responsible for identifying:
    - Duplicate invoices (same number + vendor within 90 days)
    - Amount outliers (>10% variance from PO)
    - Unknown or unapproved vendors
    - Date anomalies (future-dated, stale)
    - Pattern-based fraud indicators

    Outputs an anomaly report with severity classifications.
    """
    return Agent(
        role="Anomaly Detection Specialist",
        goal=(
            "Identify all anomalies, irregularities, and potential fraud indicators in the "
            "invoice data. Detect duplicates, amount outliers, unknown vendors, date anomalies, "
            "and other suspicious patterns. Classify each finding by severity and provide "
            "clear evidence supporting each flag. Never suppress a finding due to uncertainty."
        ),
        backstory=(
            "You are a forensic analyst specializing in financial fraud detection and accounts "
            "payable anomalies. Your career was built identifying patterns that others miss. "
            "You have uncovered duplicate payment schemes, vendor impersonation fraud, and "
            "overbilling arrangements that cost organizations millions. You approach every "
            "invoice with healthy skepticism and a systematic methodology. You understand "
            "the difference between an anomaly that needs investigation and a genuine error "
            "that needs correction, and you calibrate your severity ratings accordingly."
        ),
        llm=_DEFAULT_LLM,
        verbose=True,
        allow_delegation=False,
        max_iter=3,
    )


def create_reconciliation_agent() -> Agent:
    """
    Agent 5: Reconciliation Manager

    Responsible for generating the final reconciliation report including:
    - Matched invoices ready for payment
    - Flagged items requiring review
    - Unresolved discrepancies
    - Full audit trail summary

    This agent is the final decision point before human approval or auto-processing.
    """
    return Agent(
        role="Reconciliation Manager",
        goal=(
            "Generate a comprehensive, accurate reconciliation report that summarizes the "
            "processing of all invoices in the batch. Clearly categorize matched invoices, "
            "flagged items, and unresolved discrepancies. Ensure the full audit trail is "
            "captured and that escalation recommendations are clear and actionable. "
            "The report should be sufficient for a finance controller to make approval decisions."
        ),
        backstory=(
            "You are a senior finance manager with extensive experience in period-end close, "
            "AP reconciliation, and regulatory reporting. You have led reconciliation processes "
            "for multi-billion dollar organizations and understand that a well-prepared "
            "reconciliation package is the foundation of financial integrity. You are detail-"
            "oriented but also strategic: you highlight the most critical issues first and "
            "provide clear recommendations. You know that your output goes directly to "
            "executives for approval, so clarity and accuracy are non-negotiable."
        ),
        llm=_DEFAULT_LLM,
        verbose=True,
        allow_delegation=False,
        max_iter=3,
    )


def create_all_agents() -> dict[str, Agent]:
    """Create and return all pipeline agents as a named dictionary."""
    return {
        "document_intake": create_document_intake_agent(),
        "data_extraction": create_data_extraction_agent(),
        "validation": create_validation_agent(),
        "anomaly_detection": create_anomaly_detection_agent(),
        "reconciliation": create_reconciliation_agent(),
    }
