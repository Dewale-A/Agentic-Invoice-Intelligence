# Project Overview: Agentic Invoice Intelligence

## The Problem

Accounts payable teams process hundreds or thousands of invoices every month. Most of that work is manual: someone opens a PDF, reads the vendor name, checks the PO number, verifies the math, and passes it to a manager if the amount is large enough. Every step is a chance for an error, a delay, or worse -- a fraudulent invoice slipping through because the reviewer was moving too fast.

The root issues are familiar to anyone who has worked in finance operations:

- **Unstructured input.** Invoices arrive as PDFs, scanned images, and email attachments. Each vendor formats theirs differently.
- **Fragmented validation.** The person doing data entry is rarely the same person checking the PO balance or approving the payment.
- **Invisible governance.** Approval rules exist in policy documents and tribal knowledge, not in the system itself. When something goes wrong, the audit trail is incomplete.
- **No early warning.** Anomalies like duplicate invoices or unknown vendors are often caught late, if at all.

This project was built to solve those problems using a five-agent AI pipeline with governance embedded at every step.

---

## Why Five Agents?

Each agent in the pipeline has a single, well-defined responsibility. This separation of concerns mirrors how a well-run AP department actually works -- no single person both receives the invoice and approves the payment.

### Agent 1: Document Intake Specialist

The first agent decides whether the document is worth processing. It classifies the file type, detects whether OCR is needed for scanned images, and produces an initial quality assessment. If the OCR confidence is below 85%, the system stops here and routes the invoice to a human reviewer rather than propagating a bad extraction through the pipeline.

This is a deliberate design choice. Garbage in, garbage out. An agent that confidently extracts wrong data is worse than one that admits uncertainty.

### Agent 2: Data Extraction Analyst

This agent reads the document and pulls out the structured fields: vendor name, invoice number, date, line items, totals, PO reference, and currency. It uses the document text or OCR output from Agent 1 and produces a validated `ExtractedInvoice` object with a confidence score attached.

Rather than treating extraction as a binary pass/fail, the system tracks confidence per field. This makes downstream governance decisions richer -- you can distinguish "we extracted the vendor name confidently but the line items are unclear" from a wholesale extraction failure.

### Agent 3: Validation Officer

This agent cross-references the extracted data against the system's source-of-truth records: the approved vendor registry and the purchase order database. It checks:

- Is this vendor on the approved list?
- Does a matching PO exist?
- Does the invoice total fall within the acceptable variance from the PO amount (default: 10%)?
- Are the line item totals mathematically consistent?

A validation report is produced with field-level results. This report feeds directly into the governance engine, which decides whether to proceed, flag, or hold.

### Agent 4: Anomaly Detection Specialist

This agent looks for patterns that should not be there. It checks for duplicate invoices (same invoice number and vendor within 90 days), statistical outliers in invoice amounts relative to vendor history, future-dated invoices, and invoices from vendors who are technically approved but have no recent activity.

Anomaly detection runs after validation so it can reason about both the extracted data quality and the business logic findings from Agent 3. A $50,000 invoice from an approved vendor with a matching PO is treated very differently from a $50,000 invoice from that same vendor with no PO and a recent duplicate.

### Agent 5: Reconciliation Manager

The final agent synthesises everything into a reconciliation report. It assigns a final status to each invoice (approved, flagged, on-hold, rejected), computes batch-level statistics, and surfaces a list of exceptions that require human attention. It also generates the governance dashboard metrics.

This agent is deliberately not autonomous for high-value decisions. It produces recommendations, not final approvals. The materiality gates embedded in the governance engine ensure that invoices above certain thresholds ($5K, $25K, $100K) are always routed to the appropriate human approver -- the system never auto-approves a large invoice.

---

## The Governance Engine: Inline, Not Post-Hoc

Most automation systems apply rules at the end, after all the processing is done. This project does the opposite.

The governance engine runs between every agent stage. After intake, after extraction, after validation, and after anomaly detection. This means a high-risk signal stops the invoice early rather than letting it complete the pipeline only to be flagged at the end.

The six governance rules, evaluated in priority order:

1. **OCR confidence gate** -- Low-quality scans are held immediately. No point extracting bad data.
2. **Duplicate detection** -- Exact duplicates are blocked before any downstream work.
3. **Unknown vendor hold** -- Invoices from unregistered vendors are held pending onboarding.
4. **PO variance flag** -- Amounts that differ from the PO by more than 10% are flagged.
5. **Materiality gates** -- Invoices above dollar thresholds are routed to the right approval level.
6. **Agent confidence gate** -- Any agent reporting below 70% confidence triggers human review.

Every governance decision is written to an immutable audit log. The log is append-only by design. Nothing is deleted, nothing is modified. This is the foundation of the compliance story.

---

## Who This Is For

**Hiring managers and technical leads** will find this project demonstrates production-relevant engineering decisions: Pydantic v2 for strict data contracts, FastAPI for a clean API surface, CrewAI for multi-agent orchestration, and SQLite with a clear migration path to PostgreSQL. The architecture scales horizontally because the governance engine is stateless and the agents communicate through shared data models rather than direct coupling.

**Accounting and finance professionals** will recognise the workflow. The four-eyes principle is not bolted on -- it is built into the materiality gate logic. The audit trail is not an afterthought -- it is written by every governance decision, every agent action, and every human override. The escalation levels ($5K, $25K, $100K) are configurable and map directly to common approval authority matrices.

**Anyone evaluating AI in financial workflows** will find the governance-first design reassuring. The system is explicit about what it does not know. Confidence scores are tracked. Escalation is automatic. No invoice moves past a governance gate without a logged reason.

---

## Simulated Data

The project ships with 20 simulated vendor records and 15 purchase orders that reflect realistic enterprise patterns: software subscriptions, cloud infrastructure, professional services, marketing agencies, and facilities management. The sample invoices cover normal cases, high-value edge cases, duplicate detection scenarios, and unknown vendor scenarios.

This makes the system fully runnable without connecting to any external data source, which matters both for demos and for development.

---

## What Production Would Look Like

The current implementation uses SQLite and a local file system for simplicity. A production deployment would replace these with:

- **PostgreSQL** for the relational store, using SQLAlchemy async engine with the same query patterns
- **Object storage** (S3 or equivalent) for raw invoice files
- **A message queue** (SQS or RabbitMQ) to decouple the upload API from the processing pipeline
- **A secrets manager** for API keys rather than environment variables
- **Prometheus metrics** on agent confidence scores, governance decisions, and processing latency
- **Role-based access control** on the approval endpoints

The architecture decisions made in this reference implementation were made with this migration path in mind.
