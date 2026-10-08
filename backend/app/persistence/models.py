"""SQLAlchemy ORM models defining the database schema according to Revision 3."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.persistence.database import Base


def generate_uuid() -> str:
    """Generate a standard UUID string for primary keys."""
    return str(uuid.uuid4())


class UserOrm(Base):
    """User accounts, credentials, and pilot identities."""

    __tablename__ = "user"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)  # Nullable for dev/test simulation
    role: Mapped[str] = mapped_column(String(30), nullable=False)  # ENGINEER, QS, ACCOUNTS, REVIEWER, ADMIN
    can_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    assigned_cases: Mapped[list[VerificationCaseOrm]] = relationship(
        "VerificationCaseOrm", foreign_keys="VerificationCaseOrm.assignee_reviewer_id", back_populates="assignee"
    )
    project_assignments: Mapped[list[ProjectUserOrm]] = relationship(
        "ProjectUserOrm", foreign_keys="ProjectUserOrm.user_id", back_populates="user", cascade="all, delete-orphan"
    )
    sessions: Mapped[list[UserSessionOrm]] = relationship(
        "UserSessionOrm", back_populates="user", cascade="all, delete-orphan"
    )


class UserSessionOrm(Base):
    """Database-backed session management for revocable refresh sessions."""

    __tablename__ = "user_session"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("user.id"), nullable=False, index=True)
    session_token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(50), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    user: Mapped[UserOrm] = relationship("UserOrm", back_populates="sessions")


class ProjectUserOrm(Base):
    """Explicit project assignment mapping users to construction site projects."""

    __tablename__ = "project_user"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_user"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("project.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("user.id"), nullable=False, index=True)
    assigned_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("user.id"), nullable=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    project: Mapped[ProjectOrm] = relationship("ProjectOrm", back_populates="user_assignments")
    user: Mapped[UserOrm] = relationship("UserOrm", foreign_keys=[user_id], back_populates="project_assignments")


class ProjectOrm(Base):
    """Construction project site reference data."""

    __tablename__ = "project"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    client: Mapped[str] = mapped_column(String(200), nullable=False)
    site_location: Mapped[str] = mapped_column(String(200), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    cases: Mapped[list[VerificationCaseOrm]] = relationship("VerificationCaseOrm", back_populates="project")
    user_assignments: Mapped[list[ProjectUserOrm]] = relationship(
        "ProjectUserOrm", back_populates="project", cascade="all, delete-orphan"
    )


class SupplierOrm(Base):
    """Supplier master catalog with UAE Tax Registration Number (TRN)."""

    __tablename__ = "supplier"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    trn: Mapped[str] = mapped_column(String(20), nullable=False)  # UAE 15-digit TRN
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    cases: Mapped[list[VerificationCaseOrm]] = relationship("VerificationCaseOrm", back_populates="supplier")


class MaterialOrm(Base):
    """Material specifications catalog."""

    __tablename__ = "material"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)  # CONCRETE, STEEL, AGGREGATE, CEMENT, BLOCKS
    default_unit: Mapped[str] = mapped_column(String(20), nullable=False)
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    spec_attributes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class UnitOrm(Base):
    """Measurement units dictionary."""

    __tablename__ = "unit"

    code: Mapped[str] = mapped_column(String(20), primary_key=True)
    dimension: Mapped[str] = mapped_column(String(30), nullable=False)  # VOLUME, MASS, COUNT, LENGTH, AREA
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)


class UnitConversionOrm(Base):
    """Unit conversion factors (provisional and confirmed)."""

    __tablename__ = "unit_conversion"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    from_unit: Mapped[str] = mapped_column(String(20), ForeignKey("unit.code"), nullable=False)
    to_unit: Mapped[str] = mapped_column(String(20), ForeignKey("unit.code"), nullable=False)
    factor: Mapped[str] = mapped_column(Text, nullable=False)  # Decimal stored as string
    scope: Mapped[str] = mapped_column(String(20), nullable=False)  # GLOBAL or MATERIAL
    material_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("material.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="PROPOSED", nullable=False)  # PROPOSED, CONFIRMED, RETIRED
    confirmed_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("user.id"), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class LpoOrm(Base):
    """Local Purchase Order (LPO) master contract/order agreement."""

    __tablename__ = "lpo"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    lpo_number: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("project.id"), nullable=False, index=True)
    supplier_id: Mapped[str] = mapped_column(String(36), ForeignKey("supplier.id"), nullable=False, index=True)
    lpo_date: Mapped[str] = mapped_column(String(30), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="AED", nullable=False)
    document_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("document.id"), nullable=True)
    total_amount_cap: Mapped[str | None] = mapped_column(Text, nullable=True)  # Decimal stored as string
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("user.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    project: Mapped[ProjectOrm] = relationship("ProjectOrm")
    supplier: Mapped[SupplierOrm] = relationship("SupplierOrm")
    lines: Mapped[list[LpoLineOrm]] = relationship("LpoLineOrm", back_populates="lpo", cascade="all, delete-orphan")


class LpoLineOrm(Base):
    """LPO Line Item specifying material, agreed unit rate, and quantity cap."""

    __tablename__ = "lpo_line"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    lpo_id: Mapped[str] = mapped_column(String(36), ForeignKey("lpo.id"), nullable=False, index=True)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    material_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("material.id"), nullable=True)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    ordered_qty: Mapped[str] = mapped_column(Text, nullable=False)  # Decimal stored as string
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    agreed_unit_price: Mapped[str] = mapped_column(Text, nullable=False)  # Decimal stored as string
    line_amount_cap: Mapped[str | None] = mapped_column(Text, nullable=True)  # Decimal stored as string

    lpo: Mapped[LpoOrm] = relationship("LpoOrm", back_populates="lines")
    material: Mapped[MaterialOrm | None] = relationship("MaterialOrm")


class VerificationCaseOrm(Base):
    """Core verification case record: exactly one supplier invoice supported by 1..n DNs."""

    __tablename__ = "verification_case"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    case_ref: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("project.id"), nullable=False)
    supplier_id: Mapped[str] = mapped_column(String(36), ForeignKey("supplier.id"), nullable=False)
    lpo_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("lpo.id"), nullable=True)
    invoice_number_hint: Mapped[str | None] = mapped_column(String(100), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="AED", nullable=False)  # Fixed to AED
    lpo_required: Mapped[bool] = mapped_column(Boolean, nullable=False)  # Mandatory per case (D4)
    lpo_reason_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    lpo_reason_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="DRAFT", nullable=False)
    assignee_reviewer_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("user.id"), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("user.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    project: Mapped[ProjectOrm] = relationship("ProjectOrm", back_populates="cases")
    supplier: Mapped[SupplierOrm] = relationship("SupplierOrm", back_populates="cases")
    lpo: Mapped[LpoOrm | None] = relationship("LpoOrm")
    assignee: Mapped[UserOrm | None] = relationship(
        "UserOrm", foreign_keys=[assignee_reviewer_id], back_populates="assigned_cases"
    )
    documents: Mapped[list[DocumentOrm]] = relationship("DocumentOrm", back_populates="case", cascade="all, delete-orphan", foreign_keys="DocumentOrm.case_id")
    runs: Mapped[list[VerificationRunOrm]] = relationship("VerificationRunOrm", back_populates="case", cascade="all, delete-orphan")
    reviews: Mapped[list[ReviewOrm]] = relationship("ReviewOrm", back_populates="case", cascade="all, delete-orphan")
    line_links: Mapped[list[LineLinkOrm]] = relationship("LineLinkOrm", back_populates="case", cascade="all, delete-orphan")


class DocumentOrm(Base):
    """Document metadata attached to a verification case."""

    __tablename__ = "document"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    case_id: Mapped[str] = mapped_column(String(36), ForeignKey("verification_case.id"), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(20), nullable=False)  # INVOICE, DELIVERY_NOTE, LPO
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)  # Used for integrity and reuse detection
    page_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    quarantine_status: Mapped[str] = mapped_column(String(30), default="CLEAN", nullable=False)  # QUARANTINED, SCANNING, CLEAN, INFECTED, REJECTED
    security_scan_result: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_quarantined: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    uploaded_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("user.id"), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    extraction_status: Mapped[str] = mapped_column(String(30), default="PENDING", nullable=False)
    extraction_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    extractor_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    data_review_status: Mapped[str] = mapped_column(String(30), default="UNREVIEWED", nullable=False)
    reference_no_normalized: Mapped[str | None] = mapped_column(String(100), nullable=True)  # For cross-case reuse
    superseded_by_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("document.id"), nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    case: Mapped[VerificationCaseOrm] = relationship("VerificationCaseOrm", back_populates="documents", foreign_keys=[case_id])
    line_items: Mapped[list[LineItemOrm]] = relationship("LineItemOrm", back_populates="document", cascade="all, delete-orphan")


class LineItemOrm(Base):
    """Document line items extracted from an invoice or delivery note."""

    __tablename__ = "line_item"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("document.id"), nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), default="MATERIAL", nullable=False)  # MATERIAL, CHARGE, UNKNOWN
    material_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("material.id"), nullable=True)
    deleted_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # M4B Site receipt and engineering verification metadata
    storekeeper_ticket_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    gate_entry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    storekeeper_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    storekeeper_user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("user.id"), nullable=True)
    engineer_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    engineer_user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("user.id"), nullable=True)
    rejected_qty: Mapped[str | None] = mapped_column(Text, nullable=True)  # Decimal stored as string
    rejection_reason_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    has_rejection_evidence: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    document: Mapped[DocumentOrm] = relationship("DocumentOrm", back_populates="line_items")
    fields: Mapped[list[ExtractedFieldOrm]] = relationship("ExtractedFieldOrm", back_populates="line_item")


class ExtractedFieldOrm(Base):
    """Extracted header or line item fields with provenance."""

    __tablename__ = "extracted_field"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("document.id"), nullable=False)
    line_item_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("line_item.id"), nullable=True)
    field_key: Mapped[str] = mapped_column(String(100), nullable=False)
    raw_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_type: Mapped[str] = mapped_column(String(30), nullable=False)  # DECIMAL, STRING, DATE, TRN
    confidence: Mapped[str | None] = mapped_column(String(10), nullable=True)  # Decimal stored as string
    status: Mapped[str] = mapped_column(String(30), default="EXTRACTED", nullable=False)  # EXTRACTED, CONFIRMED, CORRECTED, MISSING
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_bbox: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    method: Mapped[str] = mapped_column(String(30), default="MOCK", nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("user.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    line_item: Mapped[LineItemOrm | None] = relationship("LineItemOrm", back_populates="fields")
    revisions: Mapped[list[FieldRevisionOrm]] = relationship("FieldRevisionOrm", back_populates="field")


class FieldRevisionOrm(Base):
    """Audit trail for field corrections and human reviews."""

    __tablename__ = "field_revision"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    field_id: Mapped[str] = mapped_column(String(36), ForeignKey("extracted_field.id"), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    old_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    new_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reason_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("user.id"), nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    field: Mapped[ExtractedFieldOrm] = relationship("ExtractedFieldOrm", back_populates="revisions")


class LineLinkOrm(Base):
    """Reconciliation link between an invoice line and a delivery note line."""

    __tablename__ = "line_link"
    __table_args__ = (
        # Provisional prototype rule P2: each DN line appears in at most one confirmed link per case
        UniqueConstraint("case_id", "dn_line_id", name="uq_case_dn_line_link"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    case_id: Mapped[str] = mapped_column(String(36), ForeignKey("verification_case.id"), nullable=False)
    invoice_line_id: Mapped[str] = mapped_column(String(36), ForeignKey("line_item.id"), nullable=False)
    dn_line_id: Mapped[str] = mapped_column(String(36), ForeignKey("line_item.id"), nullable=False)
    lpo_line_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("lpo_line.id"), nullable=True)
    link_method: Mapped[str] = mapped_column(String(30), default="MANUAL", nullable=False)  # EXACT_REF, MATERIAL_CODE, MANUAL
    status: Mapped[str] = mapped_column(String(30), default="CONFIRMED", nullable=False)
    confirmed_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("user.id"), nullable=True)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    case: Mapped[VerificationCaseOrm] = relationship("VerificationCaseOrm", back_populates="line_links")
    lpo_line: Mapped[LpoLineOrm | None] = relationship("LpoLineOrm")


class VerificationRunOrm(Base):
    """Immutable record of an automated verification run execution."""

    __tablename__ = "verification_run"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    case_id: Mapped[str] = mapped_column(String(36), ForeignKey("verification_case.id"), nullable=False)
    run_no: Mapped[int] = mapped_column(Integer, nullable=False)
    ruleset_version: Mapped[str] = mapped_column(String(50), nullable=False)
    active_checks: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str] = mapped_column(String(100), nullable=False)
    summary_labels: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    started_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("user.id"), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    case: Mapped[VerificationCaseOrm] = relationship("VerificationCaseOrm", back_populates="runs")
    findings: Mapped[list[FindingOrm]] = relationship("FindingOrm", back_populates="run", cascade="all, delete-orphan")
    review: Mapped[ReviewOrm | None] = relationship("ReviewOrm", back_populates="run", uselist=False)


class FindingOrm(Base):
    """Immutable finding item produced by a verification run."""

    __tablename__ = "finding"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("verification_run.id"), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    rule_code: Mapped[str] = mapped_column(String(50), nullable=False)
    outcome: Mapped[str] = mapped_column(String(30), nullable=False)  # MATCH, MISMATCH, MISSING_EVIDENCE, UNCERTAIN, NOT_CHECKED, etc.
    severity: Mapped[str] = mapped_column(String(20), nullable=False)  # INFO, WARNING, CRITICAL
    subject_type: Mapped[str] = mapped_column(String(50), nullable=False)
    subject_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    expected: Mapped[str | None] = mapped_column(Text, nullable=True)
    actual: Mapped[str | None] = mapped_column(Text, nullable=True)
    difference: Mapped[str | None] = mapped_column(Text, nullable=True)
    difference_pct: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    conversion_used: Mapped[str | None] = mapped_column(Text, nullable=True)
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    rule_status: Mapped[str] = mapped_column(String(20), default="CONFIRMED", nullable=False)  # CONFIRMED or PROVISIONAL
    numeric_policy: Mapped[str | None] = mapped_column(String(30), nullable=True)  # QTY_EXACT, MONEY_ROUND_2DP_HALF_UP

    run: Mapped[VerificationRunOrm] = relationship("VerificationRunOrm", back_populates="findings")
    dispositions: Mapped[list[FindingDispositionOrm]] = relationship("FindingDispositionOrm", back_populates="finding")


class ReviewOrm(Base):
    """Immutable human reviewer sign-off (Unique constraint: exactly one review per run)."""

    __tablename__ = "review"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_review_run_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    case_id: Mapped[str] = mapped_column(String(36), ForeignKey("verification_case.id"), nullable=False)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("verification_run.id"), nullable=False)
    reviewer_id: Mapped[str] = mapped_column(String(36), ForeignKey("user.id"), nullable=False)
    outcome: Mapped[str] = mapped_column(String(50), nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    declaration_accepted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    sod_warning: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    qualifiers: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    case: Mapped[VerificationCaseOrm] = relationship("VerificationCaseOrm", back_populates="reviews")
    run: Mapped[VerificationRunOrm] = relationship("VerificationRunOrm", back_populates="review")
    reviewer: Mapped[UserOrm] = relationship("UserOrm")
    dispositions: Mapped[list[FindingDispositionOrm]] = relationship("FindingDispositionOrm", back_populates="review")


class FindingDispositionOrm(Base):
    """Reviewer disposition attached to a specific finding (e.g. REUSE_JUSTIFIED, MANUAL_VAT_CHECK)."""

    __tablename__ = "finding_disposition"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    review_id: Mapped[str] = mapped_column(String(36), ForeignKey("review.id"), nullable=False)
    finding_id: Mapped[str] = mapped_column(String(36), ForeignKey("finding.id"), nullable=False)
    disposition: Mapped[str] = mapped_column(String(50), nullable=False)  # REUSE_JUSTIFIED, MANUAL_VAT_CHECK_DOCUMENTED, etc.
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    manual_check_items: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    review: Mapped[ReviewOrm] = relationship("ReviewOrm", back_populates="dispositions")
    finding: Mapped[FindingOrm] = relationship("FindingOrm", back_populates="dispositions")


class AuditEventOrm(Base):
    """Append-only audit trail logging all lifecycle and review events."""

    __tablename__ = "audit_event"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("user.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(100), nullable=False)
    case_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("verification_case.id"), nullable=True)
    before_state: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    after_state: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
