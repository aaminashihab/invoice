"""Domain models and value objects for the verification engine (pure Python, zero I/O)."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any


class DocumentType(str, Enum):
    INVOICE = "INVOICE"
    DELIVERY_NOTE = "DELIVERY_NOTE"
    LPO = "LPO"


class FieldStatus(str, Enum):
    EXTRACTED = "EXTRACTED"
    CONFIRMED = "CONFIRMED"
    CORRECTED = "CORRECTED"
    MISSING = "MISSING"


class FindingOutcome(str, Enum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    UNIT_INCOMPATIBLE = "UNIT_INCOMPATIBLE"
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    UNCERTAIN = "UNCERTAIN"
    NOT_CHECKED = "NOT_CHECKED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class FindingCategory(str, Enum):
    COMPLETENESS = "COMPLETENESS"
    PARTY = "PARTY"
    PROJECT = "PROJECT"
    REFERENCE = "REFERENCE"
    DN_REUSE = "DN_REUSE"
    DUPLICATE = "DUPLICATE"
    MATERIAL = "MATERIAL"
    UNIT = "UNIT"
    QTY_LINE = "QTY_LINE"
    QTY_TOTAL = "QTY_TOTAL"
    LPO = "LPO"
    PRICE = "PRICE"
    ARITHMETIC = "ARITHMETIC"
    VAT = "VAT"
    CURRENCY = "CURRENCY"


class RuleStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    PROVISIONAL = "PROVISIONAL"


class NumericPolicy(str, Enum):
    QTY_EXACT = "QTY_EXACT"
    MONEY_ROUND_2DP_HALF_UP = "MONEY_ROUND_2DP_HALF_UP"


class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class ValueWithTrust:
    """Represents a value with its extraction/confirmation status and provenance."""
    value: Any
    status: FieldStatus
    confidence: float | None = None
    document_id: str | None = None
    page: int | None = None
    field_key: str | None = None
    raw_text: str | None = None

    @property
    def is_absent(self) -> bool:
        return self.value is None or self.status == FieldStatus.MISSING

    @property
    def is_trusted(self) -> bool:
        """Only human-confirmed or corrected values are trusted. Extracted/unconfirmed is NOT trusted."""
        if self.is_absent:
            return False
        return self.status in (FieldStatus.CONFIRMED, FieldStatus.CORRECTED)


@dataclass(frozen=True)
class ProvenanceRef:
    document_id: str
    label: str
    page: int | None = None
    field_id: str | None = None
    value: str | None = None


@dataclass(frozen=True)
class Finding:
    category: FindingCategory
    rule_code: str
    outcome: FindingOutcome
    severity: Severity
    message: str
    subject_type: str | None = None
    subject_id: str | None = None
    expected_value: str | None = None
    actual_value: str | None = None
    difference: str | None = None
    difference_pct: str | None = None
    unit: str | None = None
    conversion_used: dict[str, Any] | None = None
    sources: list[ProvenanceRef] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    rule_status: RuleStatus = RuleStatus.CONFIRMED
    numeric_policy: NumericPolicy | None = None


@dataclass(frozen=True)
class DNLineSnapshot:
    line_id: str
    document_id: str
    dn_number: str
    line_no: int
    material_code: str
    description: str
    delivered_qty: ValueWithTrust
    rejected_qty: ValueWithTrust | None = None
    rejection_evidence_type: str | None = None  # e.g. "DN_REJECTED_COLUMN", "DN_SIGNED_REMARK"
    has_rejection_evidence: bool = False
    unit: str = "m3"
    spec_attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InvoiceLineSnapshot:
    line_id: str
    document_id: str
    invoice_number: str
    line_no: int
    material_code: str
    description: str
    invoiced_qty: ValueWithTrust
    unit: str
    unit_price: ValueWithTrust
    line_amount: ValueWithTrust
    kind: str = "MATERIAL"  # MATERIAL or CHARGE
    dn_reference: str | None = None
    spec_attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LPOLineSnapshot:
    line_id: str
    document_id: str
    lpo_number: str
    line_no: int
    material_code: str
    description: str
    ordered_qty: ValueWithTrust
    unit: str
    unit_price: ValueWithTrust
    previously_invoiced_qty: Decimal = Decimal(0)


@dataclass(frozen=True)
class CaseSnapshot:
    case_id: str
    project_id: str
    project_name: str
    supplier_id: str
    supplier_name: str
    supplier_trn: ValueWithTrust
    invoice_number: ValueWithTrust
    invoice_date: ValueWithTrust
    invoice_currency: ValueWithTrust
    subtotal: ValueWithTrust
    tax_amount: ValueWithTrust
    grand_total: ValueWithTrust
    lpo_required: bool
    lpo_reason_code: str | None = None
    lpo_reason_text: str | None = None
    invoice_lines: list[InvoiceLineSnapshot] = field(default_factory=list)
    dn_lines: list[DNLineSnapshot] = field(default_factory=list)
    lpo_lines: list[LPOLineSnapshot] = field(default_factory=list)
    # Confirmed line links: invoice_line_id -> list of dn_line_ids
    confirmed_links: dict[str, list[str]] = field(default_factory=dict)
    # LPO line links: invoice_line_id -> lpo_line_id
    lpo_line_links: dict[str, str] = field(default_factory=dict)
    # Cross-case reuse index: (supplier_trn/id, normalized_dn_number) -> list of other_case_refs
    cross_case_dn_index: dict[str, list[str]] = field(default_factory=dict)
    # Cross-case file sha256 index: sha256 -> list of other_case_refs
    cross_case_sha_index: dict[str, list[str]] = field(default_factory=dict)
    dn_file_hashes: dict[str, str] = field(default_factory=dict)  # doc_id -> sha256
