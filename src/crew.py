"""
Crew orchestration for the AgenticInvoiceIntelligence pipeline.

Design decision: governance is applied INLINE between each agent stage via
a custom execution wrapper rather than as a post-processing step. This means:
  1. The Crew runs each task sequentially.
  2. After each agent completes its stage, the GovernanceEngine evaluates the
     current invoice state.
  3. If a governance gate fires, the invoice status is updated immediately and
     the decision is logged to the immutable audit trail.
  4. High-risk invoices (blocked/escalated) are still carried through the pipeline
     for reporting purposes, but their status prevents auto-approval.

This approach preserves full CrewAI observability while adding governance as
a first-class concern at every pipeline boundary.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from crewai import Crew, Process

from src.agents.definitions import create_all_agents
from src.data.database import (
    bootstrap,
    save_agent_decision,
    update_invoice_status,
    upsert_invoice,
)
from src.governance.audit import (
    log_agent_stage,
    log_invoice_received,
    log_status_change,
)
from src.governance.engine import GovernanceEngine
from src.models.schemas import (
    AgentDecision,
    AgentRole,
    AnomalyReport,
    ExtractedInvoice,
    InvoiceStatus,
    ReconciliationItem,
    ReconciliationReport,
    ValidationReport,
    ValidationStatus,
)
from src.tasks.definitions import create_pipeline_tasks
from src.tools.anomaly_tools import analyze_anomalies
from src.tools.document_tools import process_document
from src.tools.extraction_tools import extract_invoice_fields
from src.tools.validation_tools import validate_invoice


# ---------------------------------------------------------------------------
# Crew runner
# ---------------------------------------------------------------------------


class InvoiceProcessingCrew:
    """
    Orchestrates the 5-agent invoice processing pipeline with inline governance.

    Usage:
        crew = InvoiceProcessingCrew()
        report = crew.process_batch(["invoice1.pdf", "invoice2.pdf"])
    """

    def __init__(self):
        bootstrap()  # Ensure DB is initialized with seed data
        self.governance = GovernanceEngine()

    def process_invoice(self, file_path: Path) -> tuple[ExtractedInvoice, AnomalyReport, list]:
        """
        Process a single invoice through the full pipeline with inline governance.
        Returns (extracted_invoice, anomaly_report, governance_decisions).
        """
        all_governance_decisions = []
        invoice_id = str(uuid4())

        # Stage 1: Document Intake
        stage_start = time.time()
        log_invoice_received(invoice_id, file_path.name)

        doc_result = process_document(file_path)

        intake_time_ms = int((time.time() - stage_start) * 1000)
        intake_confidence = min(
            doc_result["ocr_confidence"],
            doc_result["classification_confidence"] + 0.2,  # boost for digital PDFs
        )

        # Build a preliminary invoice for governance
        invoice = ExtractedInvoice(
            invoice_id=invoice_id,  # type: ignore[arg-type]
            source_filename=doc_result["filename"],
            document_type=doc_result["document_type"],
            raw_text=doc_result["raw_text"],
            ocr_used=doc_result["ocr_used"],
            ocr_confidence=doc_result["ocr_confidence"],
            extraction_confidence=intake_confidence,
            status=InvoiceStatus.PROCESSING,
        )

        # Governance Gate 1: OCR confidence
        gov_decisions = self.governance.evaluate_post_intake(invoice)
        all_governance_decisions.extend(gov_decisions)

        log_agent_stage(
            invoice_id,
            AgentRole.DOCUMENT_INTAKE,
            "document_intake",
            f"Processed {file_path.name}: type={doc_result['document_type'].value}, "
            f"ocr_used={doc_result['ocr_used']}, ocr_conf={doc_result['ocr_confidence']:.2f}",
            intake_confidence,
            {"ocr_used": doc_result["ocr_used"], "ocr_confidence": doc_result["ocr_confidence"]},
        )
        _save_agent_decision(invoice_id, AgentRole.DOCUMENT_INTAKE, intake_confidence, intake_time_ms)

        # Stage 2: Data Extraction
        stage_start = time.time()
        invoice = extract_invoice_fields(
            raw_text=doc_result["raw_text"],
            source_filename=doc_result["filename"],
            document_type=doc_result["document_type"],
            ocr_used=doc_result["ocr_used"],
            ocr_confidence=doc_result["ocr_confidence"],
        )
        # Preserve the invoice_id we assigned
        invoice = invoice.model_copy(update={"invoice_id": invoice_id})  # type: ignore[arg-type]
        extraction_time_ms = int((time.time() - stage_start) * 1000)

        # Governance Gate 2: Duplicate + extraction confidence
        gov_decisions = self.governance.evaluate_post_extraction(
            invoice, invoice.extraction_confidence
        )
        all_governance_decisions.extend(gov_decisions)

        log_agent_stage(
            invoice_id,
            AgentRole.DATA_EXTRACTION,
            "data_extraction",
            f"Extracted: vendor='{invoice.vendor_name}', invoice#='{invoice.invoice_number}', "
            f"total={invoice.total}, confidence={invoice.extraction_confidence:.2f}",
            invoice.extraction_confidence,
        )
        _save_agent_decision(
            invoice_id, AgentRole.DATA_EXTRACTION, invoice.extraction_confidence, extraction_time_ms
        )

        # Stage 3: Validation
        stage_start = time.time()
        validation_report = validate_invoice(invoice)
        validation_time_ms = int((time.time() - stage_start) * 1000)

        # Governance Gate 3: Vendor + PO variance + confidence
        gov_decisions = self.governance.evaluate_post_validation(invoice, validation_report)
        all_governance_decisions.extend(gov_decisions)

        log_agent_stage(
            invoice_id,
            AgentRole.VALIDATION,
            "validation",
            f"Validation: {validation_report.overall_status.value}, "
            f"vendor_approved={validation_report.vendor_approved}, "
            f"po_match={validation_report.po_match}",
            validation_report.validation_confidence,
        )
        _save_agent_decision(
            invoice_id, AgentRole.VALIDATION, validation_report.validation_confidence, validation_time_ms
        )

        # Stage 4: Anomaly Detection
        stage_start = time.time()
        anomaly_report = analyze_anomalies(invoice)
        anomaly_time_ms = int((time.time() - stage_start) * 1000)

        anomaly_confidence = 1.0 - anomaly_report.overall_risk_score * 0.5

        # Governance Gate 4: Materiality + anomaly confidence
        gov_decisions = self.governance.evaluate_post_anomaly(
            invoice, anomaly_report, anomaly_confidence
        )
        all_governance_decisions.extend(gov_decisions)

        log_agent_stage(
            invoice_id,
            AgentRole.ANOMALY_DETECTION,
            "anomaly_detection",
            f"Anomalies: {len(anomaly_report.anomalies)} flags, "
            f"risk_score={anomaly_report.overall_risk_score:.2f}, "
            f"is_duplicate={anomaly_report.is_duplicate}",
            anomaly_confidence,
        )
        _save_agent_decision(
            invoice_id, AgentRole.ANOMALY_DETECTION, anomaly_confidence, anomaly_time_ms
        )

        # Determine final status from governance decisions
        final_status = self.governance.determine_final_status(all_governance_decisions)

        # Override: if validation failed and there are HIGH+ anomalies, ensure flagged
        if (
            validation_report.overall_status == ValidationStatus.FAIL
            and anomaly_report.overall_risk_score > 0.25
            and final_status == InvoiceStatus.VALIDATED
        ):
            final_status = InvoiceStatus.FLAGGED

        invoice = invoice.model_copy(update={"status": final_status})

        # Persist to database
        _persist_invoice(invoice)
        log_status_change(
            invoice_id,
            InvoiceStatus.PROCESSING.value,
            final_status.value,
            AgentRole.GOVERNANCE.value,
            f"Governance evaluation complete. {len(all_governance_decisions)} rule(s) triggered.",
        )

        return invoice, anomaly_report, all_governance_decisions

    def process_batch(self, file_paths: list[Path], batch_id: Optional[str] = None) -> ReconciliationReport:
        """
        Process a batch of invoice files and return a ReconciliationReport.

        Also runs the 5-agent CrewAI pipeline for the LLM-augmented summary.
        """
        batch_id = batch_id or f"BATCH-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"

        report = ReconciliationReport(
            batch_id=batch_id,
            total_invoices=len(file_paths),
        )

        from decimal import Decimal

        all_items: list[ReconciliationItem] = []

        for fp in file_paths:
            try:
                invoice, anomaly_report, gov_decisions = self.process_invoice(fp)

                # Determine escalation level from governance decisions
                from src.models.schemas import EscalationLevel
                escalation = EscalationLevel.NONE
                for gd in gov_decisions:
                    if gd.escalation_level != EscalationLevel.NONE:
                        escalation = gd.escalation_level
                        break

                item = ReconciliationItem(
                    invoice_id=invoice.invoice_id,
                    vendor_name=invoice.vendor_name,
                    invoice_number=invoice.invoice_number,
                    total=invoice.total,
                    status=invoice.status,
                    validation_status=None,
                    anomaly_flags=[a.anomaly_type for a in anomaly_report.anomalies],
                    escalation_level=escalation,
                    notes="; ".join(gd.reason for gd in gov_decisions) if gov_decisions else "",
                )
                all_items.append(item)

                # Tally
                if invoice.status == InvoiceStatus.APPROVED:
                    report.approved += 1
                    report.matched += 1
                elif invoice.status in (InvoiceStatus.FLAGGED, InvoiceStatus.ON_HOLD):
                    report.flagged += 1
                    report.exceptions.append(item)
                    if invoice.total:
                        report.flagged_value += invoice.total
                elif invoice.status == InvoiceStatus.REJECTED:
                    report.rejected += 1
                    report.exceptions.append(item)
                else:
                    report.matched += 1

                if invoice.total:
                    report.total_value += invoice.total

            except Exception as exc:
                # Never let one bad invoice kill the batch
                error_item = ReconciliationItem(
                    invoice_id=uuid4(),
                    vendor_name=None,
                    invoice_number=None,
                    total=None,
                    status=InvoiceStatus.REJECTED,
                    validation_status=None,
                    anomaly_flags=["processing_error"],
                    notes=f"Processing error: {exc}",
                )
                all_items.append(error_item)
                report.rejected += 1

        report.items = all_items
        report.on_hold = sum(1 for i in all_items if i.status == InvoiceStatus.ON_HOLD)

        # Stage 5: Reconciliation Manager logs its output
        log_agent_stage(
            "BATCH",
            AgentRole.RECONCILIATION,
            "reconciliation",
            f"Batch {batch_id}: {report.total_invoices} invoices, "
            f"{report.matched} matched, {report.flagged} flagged, {report.rejected} rejected. "
            f"Total value: {report.total_value}",
            confidence=0.95 if report.rejected == 0 else 0.85,
        )

        return report

    def run_crew_pipeline(self, batch_context: dict[str, Any]) -> str:
        """
        Run the full CrewAI 5-agent pipeline for LLM-augmented processing.
        Returns the final crew output string.
        """
        agents = create_all_agents()
        tasks = create_pipeline_tasks(agents, batch_context)

        crew = Crew(
            agents=list(agents.values()),
            tasks=tasks,
            process=Process.sequential,
            verbose=True,
        )

        result = crew.kickoff()
        return str(result)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _save_agent_decision(
    invoice_id: str,
    agent_role: AgentRole,
    confidence: float,
    processing_time_ms: int,
    escalated: bool = False,
    escalation_reason: Optional[str] = None,
) -> None:
    save_agent_decision({
        "decision_id": str(uuid4()),
        "invoice_id": invoice_id,
        "agent_role": agent_role.value,
        "stage_input_summary": "",
        "stage_output_summary": "",
        "confidence": confidence,
        "escalated": int(escalated),
        "escalation_reason": escalation_reason,
        "processing_time_ms": processing_time_ms,
        "timestamp": datetime.utcnow().isoformat(),
    })


def _persist_invoice(invoice: ExtractedInvoice) -> None:
    """Serialize the invoice to a DB-compatible dict and upsert."""
    import json as _json
    line_items_json = _json.dumps([li.model_dump(mode="json") for li in invoice.line_items])
    upsert_invoice({
        "invoice_id": str(invoice.invoice_id),
        "source_filename": invoice.source_filename,
        "document_type": invoice.document_type.value,
        "vendor_name": invoice.vendor_name,
        "vendor_id": invoice.vendor_id,
        "invoice_number": invoice.invoice_number,
        "invoice_date": str(invoice.invoice_date) if invoice.invoice_date else None,
        "due_date": str(invoice.due_date) if invoice.due_date else None,
        "po_number": invoice.po_number,
        "currency": invoice.currency,
        "subtotal": float(invoice.subtotal) if invoice.subtotal is not None else None,
        "tax": float(invoice.tax) if invoice.tax is not None else None,
        "total": float(invoice.total) if invoice.total is not None else None,
        "line_items_json": line_items_json,
        "extraction_confidence": invoice.extraction_confidence,
        "ocr_confidence": invoice.ocr_confidence,
        "ocr_used": int(invoice.ocr_used),
        "status": invoice.status.value,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    })
