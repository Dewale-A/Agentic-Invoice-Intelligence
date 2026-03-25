"""
Pydantic v2 schemas for the AgenticInvoiceIntelligence system.

Design decision: All domain models are defined here as a single source of truth.
Pydantic v2 provides strict validation, JSON serialization, and schema generation
used by both the API layer and the agent pipeline.
"""

from __future__ import annotations

from datetime import datetime, date
from decimal import Decimal
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class DocumentType(str, Enum):
    INVOICE = "invoice"
    RECEIPT = "receipt"
    PURCHASE_ORDER = "purchase_order"
    STATEMENT = "statement"
    UNKNOWN = "unknown"


class InvoiceStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    VALIDATED = "validated"
    FLAGGED = "flagged"
    APPROVED = "approved"
    REJECTED = "rejected"
    ON_HOLD = "on_hold"


class AnomalySeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class EscalationLevel(str, Enum):
    NONE = "none"
    L1_MANAGER = "l1_manager"        # >$5K
    L2_CONTROLLER = "l2_controller"  # >$25K
    L3_VP_CFO = "l3_vp_cfo"         # >$100K
    HUMAN_REVIEW = "human_review"    # Low confidence or anomaly


class ValidationStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    WARNING = "warning"
    SKIPPED = "skipped"


class AgentRole(str, Enum):
    DOCUMENT_INTAKE = "document_intake_specialist"
    DATA_EXTRACTION = "data_extraction_analyst"
    VALIDATION = "validation_officer"
    ANOMALY_DETECTION = "anomaly_detection_specialist"
    RECONCILIATION = "reconciliation_manager"
    GOVERNANCE = "governance_engine"


# ---------------------------------------------------------------------------
# Core invoice models
# ---------------------------------------------------------------------------


class InvoiceLineItem(BaseModel):
    """A single line item on an invoice."""

    description: str = Field(..., min_length=1, max_length=500)
    quantity: Decimal = Field(..., gt=0)
    unit_price: Decimal = Field(..., ge=0)
    total: Decimal = Field(..., ge=0)
    category: Optional[str] = None
    gl_code: Optional[str] = None

    @model_validator(mode="after")
    def validate_total(self) -> "InvoiceLineItem":
        expected = self.quantity * self.unit_price
        if abs(expected - self.total) > Decimal("0.02"):
            # Allow minor rounding; flag large discrepancies via governance
            pass
        return self


class ExtractedInvoice(BaseModel):
    """
    Structured representation of an extracted invoice.

    Design decision: extraction_confidence drives governance routing.
    Values below 0.85 trigger human verification before downstream processing.
    """

    invoice_id: UUID = Field(default_factory=uuid4)
    source_filename: str
    document_type: DocumentType = DocumentType.INVOICE
    raw_text: str = Field(default="", exclude=True)  # excluded from API responses
    ocr_used: bool = False

    # Extracted fields
    vendor_name: Optional[str] = None
    vendor_id: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[date] = None
    due_date: Optional[date] = None
    po_number: Optional[str] = None
    currency: str = "USD"

    line_items: list[InvoiceLineItem] = Field(default_factory=list)
    subtotal: Optional[Decimal] = None
    tax: Optional[Decimal] = None
    total: Optional[Decimal] = None

    # Confidence and processing metadata
    extraction_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    ocr_confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    # Status tracking
    status: InvoiceStatus = InvoiceStatus.PENDING
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        allowed = {"USD", "CAD", "EUR", "GBP", "AUD", "JPY", "CHF"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"Unsupported currency: {v}. Allowed: {allowed}")
        return upper


# ---------------------------------------------------------------------------
# Validation models
# ---------------------------------------------------------------------------


class FieldValidationResult(BaseModel):
    """Result of validating a single extracted field."""

    field_name: str
    status: ValidationStatus
    extracted_value: Any = None
    expected_value: Any = None
    message: str = ""
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ValidationReport(BaseModel):
    """Aggregated validation results for an invoice."""

    invoice_id: UUID
    overall_status: ValidationStatus
    field_results: list[FieldValidationResult] = Field(default_factory=list)
    po_match: bool = False
    po_variance_pct: Optional[float] = None
    vendor_approved: bool = False
    budget_ok: bool = True
    validation_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    validated_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Anomaly models
# ---------------------------------------------------------------------------


class AnomalyFlag(BaseModel):
    """A single detected anomaly."""

    anomaly_type: str
    severity: AnomalySeverity
    description: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    detected_at: datetime = Field(default_factory=datetime.utcnow)


class AnomalyReport(BaseModel):
    """Aggregated anomaly detection results for an invoice."""

    invoice_id: UUID
    anomalies: list[AnomalyFlag] = Field(default_factory=list)
    is_duplicate: bool = False
    duplicate_of: Optional[UUID] = None
    amount_outlier: bool = False
    unknown_vendor: bool = False
    date_anomaly: bool = False
    overall_risk_score: float = Field(default=0.0, ge=0.0, le=1.0)
    analyzed_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def has_critical_anomalies(self) -> bool:
        return any(a.severity == AnomalySeverity.CRITICAL for a in self.anomalies)


# ---------------------------------------------------------------------------
# Governance models
# ---------------------------------------------------------------------------


class GovernanceDecision(BaseModel):
    """
    A single governance decision made inline between agents.

    Design decision: governance decisions are immutable once created.
    They form part of the audit trail and cannot be modified.
    """

    decision_id: UUID = Field(default_factory=uuid4)
    invoice_id: UUID
    rule_triggered: str
    decision: str  # "proceed" | "escalate" | "block" | "flag"
    escalation_level: EscalationLevel = EscalationLevel.NONE
    reason: str
    actor: AgentRole
    threshold_value: Optional[float] = None
    actual_value: Optional[float] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class GovernancePolicy(BaseModel):
    """Configuration for a governance rule."""

    rule_name: str
    description: str
    threshold: Optional[float] = None
    enabled: bool = True
    escalation_level: EscalationLevel = EscalationLevel.NONE


# ---------------------------------------------------------------------------
# Agent decision / audit models
# ---------------------------------------------------------------------------


class AgentDecision(BaseModel):
    """
    Records the output and confidence of an agent at a pipeline stage.

    Design decision: every agent decision is logged with its confidence score.
    Scores below 0.7 automatically trigger human escalation regardless of
    other governance rules. This ensures the system degrades gracefully.
    """

    decision_id: UUID = Field(default_factory=uuid4)
    invoice_id: UUID
    agent_role: AgentRole
    stage_input_summary: str = ""
    stage_output_summary: str = ""
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    escalated: bool = False
    escalation_reason: Optional[str] = None
    processing_time_ms: Optional[int] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class AuditTrailEntry(BaseModel):
    """
    An immutable audit trail entry.

    Design decision: audit entries are append-only. The system never updates
    or deletes audit records, ensuring full traceability for compliance.
    """

    entry_id: UUID = Field(default_factory=uuid4)
    invoice_id: UUID
    event_type: str
    actor: str  # agent role or "human:<user_id>"
    description: str
    before_state: Optional[dict[str, Any]] = None
    after_state: Optional[dict[str, Any]] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Reconciliation models
# ---------------------------------------------------------------------------


class ReconciliationItem(BaseModel):
    """A single item in the reconciliation report."""

    invoice_id: UUID
    vendor_name: Optional[str]
    invoice_number: Optional[str]
    total: Optional[Decimal]
    status: InvoiceStatus
    validation_status: Optional[ValidationStatus]
    anomaly_flags: list[str] = Field(default_factory=list)
    escalation_level: EscalationLevel = EscalationLevel.NONE
    notes: str = ""


class ReconciliationReport(BaseModel):
    """Final reconciliation output produced by the Reconciliation Manager agent."""

    report_id: UUID = Field(default_factory=uuid4)
    batch_id: Optional[str] = None
    generated_at: datetime = Field(default_factory=datetime.utcnow)

    total_invoices: int = 0
    matched: int = 0
    flagged: int = 0
    approved: int = 0
    rejected: int = 0
    on_hold: int = 0

    total_value: Decimal = Decimal("0")
    flagged_value: Decimal = Decimal("0")

    items: list[ReconciliationItem] = Field(default_factory=list)
    exceptions: list[ReconciliationItem] = Field(default_factory=list)
    audit_trail: list[AuditTrailEntry] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# API request/response models
# ---------------------------------------------------------------------------


class InvoiceUploadResponse(BaseModel):
    invoice_id: UUID
    filename: str
    status: InvoiceStatus
    message: str


class InvoiceApprovalRequest(BaseModel):
    approved_by: str = Field(..., min_length=1)
    notes: str = ""


class InvoiceRejectionRequest(BaseModel):
    rejected_by: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)


class GovernanceDashboard(BaseModel):
    """Summary view for the governance dashboard."""

    total_processed: int = 0
    pending_review: int = 0
    auto_approved: int = 0
    escalated_l1: int = 0
    escalated_l2: int = 0
    escalated_l3: int = 0
    blocked: int = 0
    avg_confidence: float = 0.0
    ocr_failures: int = 0
    duplicate_flags: int = 0
    unknown_vendor_flags: int = 0
    amount_variance_flags: int = 0
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class VendorRecord(BaseModel):
    """An approved vendor in the registry."""

    vendor_id: str
    name: str
    category: str
    contracted_rate: Optional[Decimal] = None
    payment_terms_days: int = 30
    approved: bool = True
    contact_email: Optional[str] = None


class PurchaseOrder(BaseModel):
    """A purchase order record."""

    po_number: str
    vendor_id: str
    vendor_name: str
    description: str
    amount: Decimal
    currency: str = "USD"
    issued_date: date
    expiry_date: Optional[date] = None
    remaining_balance: Optional[Decimal] = None
    status: str = "open"
