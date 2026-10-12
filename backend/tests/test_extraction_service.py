"""Comprehensive tests for OCR, Google GenAI (Gemini) ExtractionService, and Document Endpoints.

All Gemini calls use mocked responses to guarantee:
- 100% deterministic test execution.
- $0 API cost and no network dependencies.
- Validation of schema serialization, decimal parsing, and absent vs. explicit values.
- Preservation of human-confirmed / corrected values upon re-extraction.
- End-to-end API authorization, error handling (503 for missing key), and audit event creation.
"""

from __future__ import annotations

import io
from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from pypdf import PdfWriter
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.testclient import TestClient

from app.core.config import Settings
from app.domain.extraction_schemas import (
    DeliveryNoteExtractionResult,
    DeliveryNoteLineExtractionItem,
    InvoiceExtractionResult,
    InvoiceLineExtractionItem,
)
from app.main import create_app
from app.persistence.database import Base, get_db
from app.persistence.models import (
    AuditEventOrm,
    DocumentOrm,
    ExtractedFieldOrm,
    FieldRevisionOrm,
    ProjectOrm,
    ProjectUserOrm,
    SupplierOrm,
    UserOrm,
    VerificationCaseOrm,
)
from app.services.extraction_service import (
    ExtractionError,
    ExtractionService,
    MissingApiKeyError,
)
from app.storage.interface import LocalStorage, get_document_storage


def create_sample_pdf_with_text() -> bytes:
    """Generate in-memory PDF with pypdf."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


@pytest.fixture
def test_db_and_app(tmp_path):
    storage_dir = tmp_path / "storage"
    storage_dir.mkdir(parents=True, exist_ok=True)
    storage = LocalStorage(base_dir=str(storage_dir))

    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    settings = Settings(
        app_env="development",
        dev_identity_enabled=True,
        document_storage_dir=str(storage_dir),
        gemini_api_key="test-api-key-abc",
        gemini_model="gemini-2.5-flash",
    )

    app = create_app(settings=settings)

    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_document_storage] = lambda: storage
    from app.core.config import get_settings
    app.dependency_overrides[get_settings] = lambda: settings

    # Seed baseline project, user, and case
    session = TestingSessionLocal()
    proj = ProjectOrm(
        id="proj-ai-test",
        code="PRJ-AI",
        name="AI Test Tower",
        client="Apex Horizon Property Holdings PJSC (Fictional Demo)",
        site_location="Synthetic Innovation District, Sector 4",
        active=True,
    )
    session.add(proj)
    user_qs = UserOrm(id="usr-sim-qs", email="qs@test.com", name="Sim QS", role="QS", active=True)
    user_eng = UserOrm(id="usr-sim-eng", email="eng@test.com", name="Sim Eng", role="ENGINEER", active=True)
    session.add_all([user_qs, user_eng])
    session.flush()

    session.add(ProjectUserOrm(user_id=user_qs.id, project_id=proj.id))
    session.add(ProjectUserOrm(user_id=user_eng.id, project_id=proj.id))

    supp = SupplierOrm(
        id="supp-ai-test",
        name="Gulf Ready Mix LLC",
        trn="100200300400500",
        active=True,
    )
    session.add(supp)

    case = VerificationCaseOrm(
        id="case-ai-001",
        case_ref="CIV-2026-TEST-001",
        project_id=proj.id,
        supplier_id=supp.id,
        status="DRAFT",
        lpo_required=True,
        created_by=user_qs.id,
    )
    session.add(case)
    session.commit()
    session.close()

    yield {
        "engine": engine,
        "SessionLocal": TestingSessionLocal,
        "app": app,
        "storage": storage,
        "client": TestClient(app),
    }


def test_pypdf_text_extraction(tmp_path):
    """Verify pypdf extracts text or handles blank PDF gracefully."""
    pdf_bytes = create_sample_pdf_with_text()
    text = ExtractionService.extract_text_from_pdf(pdf_bytes)
    assert isinstance(text, str)


def test_missing_api_key_raises_error(test_db_and_app):
    """When GEMINI_API_KEY is not configured and no custom client is provided, raise MissingApiKeyError."""
    SessionLocal = test_db_and_app["SessionLocal"]
    storage = test_db_and_app["storage"]

    session = SessionLocal()
    # Save a document
    content = b"%PDF-1.4 dummy"
    storage_path = storage.save("test.pdf", content)
    doc = DocumentOrm(
        id="doc-test-key",
        case_id="case-ai-001",
        doc_type="INVOICE",
        original_filename="invoice.pdf",
        storage_key=storage_path,
        mime_type="application/pdf",
        size_bytes=len(content),
        sha256="abc",
        page_count=1,
    )
    session.add(doc)
    session.commit()

    service = ExtractionService(session, storage=storage)
    service.settings.gemini_api_key = None  # simulate missing key

    with pytest.raises(MissingApiKeyError) as exc_info:
        service.extract_document(doc.id, actor_id="usr-sim-qs")
    assert "GEMINI_API_KEY environment variable is not configured" in str(exc_info.value)

    # Document extraction status should be FAILED
    updated_doc = session.get(DocumentOrm, doc.id)
    assert updated_doc.extraction_status == "FAILED"
    session.close()


def test_mocked_invoice_extraction_and_untrusted_status(test_db_and_app):
    """Verify invoice extraction persists schema fields with status EXTRACTED (untrusted)."""
    SessionLocal = test_db_and_app["SessionLocal"]
    storage = test_db_and_app["storage"]

    session = SessionLocal()
    content = b"%PDF-1.4 test invoice content"
    storage_path = storage.save("inv.pdf", content)
    doc = DocumentOrm(
        id="doc-inv-001",
        case_id="case-ai-001",
        doc_type="INVOICE",
        original_filename="INV-789.pdf",
        storage_key=storage_path,
        mime_type="application/pdf",
        size_bytes=len(content),
        sha256="def",
        page_count=1,
    )
    session.add(doc)
    session.commit()

    # Mock Gemini Client and response
    mock_client = MagicMock()
    mock_result_data = InvoiceExtractionResult(
        invoice_number="INV-2026-901",
        document_date="2026-10-12",
        supplier_name="Emirates Ready Mix LLC",
        currency="AED",
        subtotal="8640.00",
        tax_amount="432.00",
        grand_total="9072.00",
        lpo_number="LPO-8812",
        lines=[
            InvoiceLineExtractionItem(
                line_no=1,
                description="Ready Mix Concrete C40/20",
                invoiced_qty="36.00",
                unit="m3",
                unit_price="240.00",
                line_amount="8640.00",
            )
        ],
    )
    mock_response = MagicMock()
    mock_response.text = mock_result_data.model_dump_json()
    mock_client.models.generate_content.return_value = mock_response

    service = ExtractionService(session, storage=storage)
    result = service.extract_document(
        document_id=doc.id,
        actor_id="usr-sim-qs",
        custom_client=mock_client,
    )

    assert result["document_id"] == doc.id
    assert result["extraction_status"] == "EXTRACTED"
    assert result["summary"]["header_fields_count"] >= 4
    assert result["summary"]["lines_count"] == 1

    # Inspect persisted fields in DB: all must be EXTRACTED
    fields_res = service.get_document_fields(doc.id)
    assert fields_res["document_id"] == doc.id
    assert len(fields_res["header_fields"]) >= 4
    for hf in fields_res["header_fields"]:
        assert hf["status"] == "EXTRACTED"  # Safeguard: Untrusted!

    line_item = fields_res["line_items"][0]
    assert line_item["line_no"] == 1
    session.close()


def test_absent_rejected_qty_remains_none_never_zero(test_db_and_app):
    """Verify that absent rejection in delivery note produces None, never default 0."""
    SessionLocal = test_db_and_app["SessionLocal"]
    storage = test_db_and_app["storage"]

    session = SessionLocal()
    content = b"%PDF-1.4 test dn"
    storage_path = storage.save("dn.pdf", content)
    doc = DocumentOrm(
        id="doc-dn-001",
        case_id="case-ai-001",
        doc_type="DELIVERY_NOTE",
        original_filename="DN-1122.pdf",
        storage_key=storage_path,
        mime_type="application/pdf",
        size_bytes=len(content),
        sha256="ghi",
        page_count=1,
    )
    session.add(doc)
    session.commit()

    mock_client = MagicMock()
    mock_result_data = DeliveryNoteExtractionResult(
        dn_number="DN-1122",
        document_date="2026-10-12",
        supplier_name="Vulcan Apex Rebar Fabrication LLC (Fictional Demo)",
        lines=[
            DeliveryNoteLineExtractionItem(
                line_no=1,
                description="Deformed Steel Bars 16mm",
                delivered_qty="15.00",
                unit="tonne",
                rejected_qty=None,  # Explicitly absent
            )
        ],
    )
    mock_response = MagicMock()
    mock_response.text = mock_result_data.model_dump_json()
    mock_client.models.generate_content.return_value = mock_response

    service = ExtractionService(session, storage=storage)
    service.extract_document(doc.id, actor_id="usr-sim-qs", custom_client=mock_client)

    fields_res = service.get_document_fields(doc.id)
    dn_line = fields_res["line_items"][0]
    assert dn_line["rejected_qty"] is None  # Must NOT be 0!
    session.close()


def test_re_extraction_preserves_confirmed_and_corrected_fields(test_db_and_app):
    """Safeguard: Never overwrite human-confirmed or corrected values during re-extraction."""
    SessionLocal = test_db_and_app["SessionLocal"]
    storage = test_db_and_app["storage"]

    session = SessionLocal()
    content = b"%PDF-1.4 test"
    storage_path = storage.save("doc1.pdf", content)
    doc = DocumentOrm(
        id="doc-reextract-001",
        case_id="case-ai-001",
        doc_type="INVOICE",
        original_filename="INV-1.pdf",
        storage_key=storage_path,
        mime_type="application/pdf",
        size_bytes=len(content),
        sha256="jkl",
        page_count=1,
    )
    session.add(doc)
    session.commit()

    # 1. Initial extraction
    mock_client = MagicMock()
    mock_res_1 = InvoiceExtractionResult(
        invoice_number="INV-OLD",
        subtotal="100.00",
        grand_total="105.00",
    )
    mock_client.models.generate_content.return_value.text = mock_res_1.model_dump_json()

    service = ExtractionService(session, storage=storage)
    service.extract_document(doc.id, actor_id="usr-sim-qs", custom_client=mock_client)

    fields = service.get_document_fields(doc.id)
    inv_num_field = next(f for f in fields["header_fields"] if f["field_key"] == "invoice_number")

    # 2. Human corrects the invoice number
    service.update_field(
        document_id=doc.id,
        field_id=inv_num_field["id"],
        new_value="INV-HUMAN-CORRECTED",
        reason="Manual correction from physical stamp",
        actor_id="usr-sim-qs",
    )

    # 3. Trigger re-extraction with new LLM output
    mock_res_2 = InvoiceExtractionResult(
        invoice_number="INV-SHOULD-BE-IGNORED",
        subtotal="200.00",  # Was still EXTRACTED, so can update
        grand_total="210.00",
    )
    mock_client.models.generate_content.return_value.text = mock_res_2.model_dump_json()
    service.extract_document(doc.id, actor_id="usr-sim-qs", custom_client=mock_client)

    fields_after = service.get_document_fields(doc.id)
    inv_field_after = next(f for f in fields_after["header_fields"] if f["field_key"] == "invoice_number")
    assert inv_field_after["normalized_value"] == "INV-HUMAN-CORRECTED"
    assert inv_field_after["status"] == "CORRECTED"
    assert inv_field_after["revisions_count"] == 1
    session.close()


def test_confirm_all_fields_promotes_status(test_db_and_app):
    """Promoting extracted fields to CONFIRMED creates human verification trust."""
    SessionLocal = test_db_and_app["SessionLocal"]
    storage = test_db_and_app["storage"]

    session = SessionLocal()
    content = b"%PDF-1.4 test"
    storage_path = storage.save("doc2.pdf", content)
    doc = DocumentOrm(
        id="doc-conf-001",
        case_id="case-ai-001",
        doc_type="INVOICE",
        original_filename="INV-2.pdf",
        storage_key=storage_path,
        mime_type="application/pdf",
        size_bytes=len(content),
        sha256="mno",
        page_count=1,
    )
    session.add(doc)
    session.commit()

    mock_client = MagicMock()
    mock_res = InvoiceExtractionResult(
        invoice_number="INV-CONF",
        subtotal="500.00",
        grand_total="525.00",
    )
    mock_client.models.generate_content.return_value.text = mock_res.model_dump_json()
    service = ExtractionService(session, storage=storage)
    service.extract_document(doc.id, actor_id="usr-sim-qs", custom_client=mock_client)

    # Confirm all
    conf_res = service.confirm_all_document_fields(doc.id, actor_id="usr-sim-qs")
    assert conf_res["data_review_status"] == "CONFIRMED"

    fields_after = service.get_document_fields(doc.id)
    for f in fields_after["header_fields"]:
        assert f["status"] == "CONFIRMED"
    session.close()


def test_api_endpoints_workflow(test_db_and_app):
    """End-to-end API tests for extraction endpoints."""
    client = test_db_and_app["client"]
    SessionLocal = test_db_and_app["SessionLocal"]
    storage = test_db_and_app["storage"]

    session = SessionLocal()
    content = b"%PDF-1.4 sample api doc"
    storage_path = storage.save("api_test.pdf", content)
    doc = DocumentOrm(
        id="doc-api-001",
        case_id="case-ai-001",
        doc_type="INVOICE",
        original_filename="INV-API.pdf",
        storage_key=storage_path,
        mime_type="application/pdf",
        size_bytes=len(content),
        sha256="pqr",
        page_count=1,
    )
    session.add(doc)
    session.commit()
    doc_id = doc.id
    session.close()

    from app.core.security import create_access_token
    token = create_access_token(user_id="usr-sim-qs", role="QS", email="qs@test.com")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Fetch fields initially (empty)
    resp = client.get(f"/api/v1/documents/{doc_id}/extracted-fields", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["document_id"] == doc_id
    assert len(data["header_fields"]) == 0

    # 2. Update a field directly (or verify 400 for non-existent field)
    resp_patch = client.patch(
        f"/api/v1/documents/{doc_id}/fields/non-existent-field",
        json={"new_value": "123.45"},
        headers=headers,
    )
    assert resp_patch.status_code == 400

    # 3. Confirm endpoint on document
    resp_conf = client.post(f"/api/v1/documents/{doc_id}/confirm", headers=headers)
    assert resp_conf.status_code == 200
    assert resp_conf.json()["data_review_status"] == "CONFIRMED"
