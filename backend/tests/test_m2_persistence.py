"""Automated tests for Milestone M2: Persistence & Seed Data."""

from __future__ import annotations

import pytest
from datetime import datetime
from decimal import Decimal
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from starlette.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.persistence.database import Base, get_db
from app.persistence.models import (
    AuditEventOrm,
    DocumentOrm,
    FindingDispositionOrm,
    FindingOrm,
    LineItemOrm,
    LineLinkOrm,
    ReviewOrm,
    UserOrm,
    VerificationCaseOrm,
    VerificationRunOrm,
)
from app.persistence.repositories import (
    AuditRepository,
    CaseRepository,
    ReviewRepository,
    RunRepository,
)
from app.persistence.seed import seed_database


@pytest.fixture
def in_memory_session():
    """Isolated in-memory SQLite database session with enforced foreign keys."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    # Enable SQLite foreign keys
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys = ON;")

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def test_seed_database_is_idempotent(in_memory_session):
    """Seed data can be executed repeatedly without errors or duplicate rows."""
    first_run = seed_database(in_memory_session)
    assert first_run["users"] == 6
    assert first_run["projects"] == 4
    assert first_run["suppliers"] == 5
    assert first_run["cases"] >= 4

    # Run again on the same session
    second_run = seed_database(in_memory_session)
    assert second_run["users"] == 0
    assert second_run["projects"] == 0
    assert second_run["suppliers"] == 0
    assert second_run["cases"] == 0

    # Verify total count is preserved
    users = in_memory_session.scalars(select(UserOrm)).all()
    assert len(users) == 6


def test_dn_line_linked_twice_in_same_case_is_prevented_by_constraint(in_memory_session):
    """Unique constraint uq_case_dn_line_link prevents linking the same DN line twice in a case."""
    seed_database(in_memory_session)

    # Fetch existing case
    case = in_memory_session.scalars(select(VerificationCaseOrm)).first()
    assert case is not None

    # Create dummy document and line items
    doc = DocumentOrm(
        id="doc-test-01",
        case_id=case.id,
        doc_type="DELIVERY_NOTE",
        original_filename="DN-TEST.pdf",
        storage_key="test_dn.pdf",
        mime_type="application/pdf",
        size_bytes=1000,
        sha256="testsha256",
    )
    in_memory_session.add(doc)
    in_memory_session.flush()

    line_inv_1 = LineItemOrm(id="li-inv-1", document_id=doc.id, line_no=1, kind="MATERIAL")
    line_inv_2 = LineItemOrm(id="li-inv-2", document_id=doc.id, line_no=2, kind="MATERIAL")
    line_dn_1 = LineItemOrm(id="li-dn-1", document_id=doc.id, line_no=1, kind="MATERIAL")
    in_memory_session.add_all([line_inv_1, line_inv_2, line_dn_1])
    in_memory_session.flush()

    # Link 1: inv 1 -> dn 1 (allowed)
    link1 = LineLinkOrm(
        case_id=case.id,
        invoice_line_id=line_inv_1.id,
        dn_line_id=line_dn_1.id,
        status="CONFIRMED",
    )
    in_memory_session.add(link1)
    in_memory_session.flush()

    # Link 2: inv 2 -> dn 1 in SAME case (forbidden by unique constraint)
    link2 = LineLinkOrm(
        case_id=case.id,
        invoice_line_id=line_inv_2.id,
        dn_line_id=line_dn_1.id,
        status="CONFIRMED",
    )
    in_memory_session.add(link2)

    with pytest.raises(IntegrityError):
        in_memory_session.flush()

    in_memory_session.rollback()


def test_one_review_per_run_unique_constraint(in_memory_session):
    """Unique constraint uq_review_run_id enforces exactly one review per verification run."""
    seed_database(in_memory_session)

    case = in_memory_session.scalars(select(VerificationCaseOrm)).first()
    reviewer = in_memory_session.scalars(select(UserOrm).where(UserOrm.can_review.is_(True))).first()
    assert reviewer is not None

    run = VerificationRunOrm(
        id="run-unique-test",
        case_id=case.id,
        run_no=99,
        ruleset_version="1.0.0-draft",
        active_checks={},
        input_snapshot={},
        input_hash="hash99",
        summary="Test Run",
        summary_labels=["Test"],
    )
    in_memory_session.add(run)
    in_memory_session.flush()

    review1 = ReviewOrm(
        id="rev-1",
        case_id=case.id,
        run_id=run.id,
        reviewer_id=reviewer.id,
        outcome="VERIFIED_NO_EXCEPTIONS",
        comment="Initial authorized review sign-off.",
        declaration_accepted=True,
    )
    in_memory_session.add(review1)
    in_memory_session.flush()

    # Attempt second review for the same run
    review2 = ReviewOrm(
        id="rev-2",
        case_id=case.id,
        run_id=run.id,
        reviewer_id=reviewer.id,
        outcome="REJECTED",
        comment="Duplicate review attempt on same run.",
        declaration_accepted=True,
    )
    in_memory_session.add(review2)

    with pytest.raises(IntegrityError):
        in_memory_session.flush()

    in_memory_session.rollback()


def test_findings_persist_rule_status_and_numeric_policy(in_memory_session):
    """Findings capture rule_status ('CONFIRMED'/'PROVISIONAL') and numeric_policy."""
    seed_database(in_memory_session)

    repo = RunRepository(in_memory_session)
    c1 = in_memory_session.scalars(select(VerificationCaseOrm).where(VerificationCaseOrm.case_ref == "VC-2026-00001")).first()
    latest_run = repo.get_latest_for_case(c1.id)
    assert latest_run is not None

    finding = latest_run.findings[0]
    assert finding.rule_status == "CONFIRMED"
    assert finding.numeric_policy == "QTY_EXACT"


def test_permanent_dn_reuse_audit_finding_retention(in_memory_session):
    """Delivery note reuse findings and audit events are permanent in history."""
    seed_database(in_memory_session)

    case_reuse = in_memory_session.scalars(
        select(VerificationCaseOrm).where(VerificationCaseOrm.case_ref == "VC-2026-00004")
    ).first()
    assert case_reuse is not None

    audit_repo = AuditRepository(in_memory_session)
    events = audit_repo.list_for_case(case_reuse.id)
    assert len(events) >= 1

    reuse_event = next((e for e in events if e.action == "DN_REUSE_FLAGGED"), None)
    assert reuse_event is not None
    assert reuse_event.after_state["conflict_case"] == "VC-2026-00012"
    assert reuse_event.after_state["rule"] == "C1_PERMANENT"


def test_cases_api_endpoints(tmp_path):
    """Test GET /api/v1/cases and GET /api/v1/cases/{id} using an isolated test DB."""
    test_db_path = tmp_path / "m2_cases_test.db"
    test_engine = create_engine(
        f"sqlite:///{test_db_path}",
        connect_args={"check_same_thread": False},
    )
    with test_engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys = ON;")

    Base.metadata.create_all(bind=test_engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    with TestingSession() as session:
        seed_database(session)

    settings = Settings(
        app_env="development",
        dev_identity_enabled=True,
        database_url=f"sqlite:///{test_db_path}",
    )
    app = create_app(settings)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        resp = client.get("/api/v1/cases")
        assert resp.status_code == 200
        data = resp.json()
        assert data["synthetic_data_only"] is True
        assert len(data["cases"]) >= 5

        case_id = data["cases"][0]["id"]
        detail_resp = client.get(f"/api/v1/cases/{case_id}")
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        assert detail["case"]["id"] == case_id
        assert "project" in detail["case"]
        assert "supplier" in detail["case"]
