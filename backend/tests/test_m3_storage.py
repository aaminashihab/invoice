"""Automated test suite for Milestone M3: Storage & Document Uploads."""

from __future__ import annotations

import io
import pytest
from PIL import Image
from pypdf import PdfWriter
from starlette.testclient import TestClient

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.main import create_app
from app.persistence.database import Base, get_db
from app.persistence.models import AuditEventOrm, DocumentOrm, VerificationCaseOrm
from app.persistence.seed import (
    SYNTHETIC_DOCUMENT_FILES,
    ensure_synthetic_storage_files,
    generate_synthetic_pdf_bytes,
    seed_database,
)
from app.services.document_service import DocumentService
from app.storage.interface import LocalStorage, StorageSecurityError, get_document_storage
from app.storage.validator import (
    CorruptDocumentError,
    EncryptedDocumentError,
    FileTooLargeError,
    PageLimitExceededError,
    UnsupportedMediaTypeError,
    validate_uploaded_document,
)


def create_dummy_pdf(pages: int = 1, password: str | None = None) -> bytes:
    """Generate synthetic in-memory PDF bytes."""
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    if password:
        writer.encrypt(password)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def create_dummy_image(fmt: str = "PNG") -> bytes:
    """Generate synthetic in-memory image bytes."""
    img = Image.new("RGB", (20, 20), color="teal")
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 1. Storage Interface Tests
# ---------------------------------------------------------------------------

def test_local_storage_crud_and_traversal_safety(tmp_path):
    storage = LocalStorage(base_dir=tmp_path)

    # Save and read
    key = "folder/test_doc.bin"
    payload = b"synthetic storage payload"
    storage.save(key, payload)

    assert storage.exists(key) is True
    assert storage.read(key) == payload

    # Delete
    assert storage.delete(key) is True
    assert storage.exists(key) is False

    # Absolute path resolution inside base_dir
    abs_key = str(tmp_path / "abs_doc.bin")
    storage.save(abs_key, payload)
    assert storage.exists(abs_key) is True
    assert storage.read(abs_key) == payload
    assert storage.delete(abs_key) is True
    assert storage.exists(abs_key) is False

    # Directory traversal prevention
    with pytest.raises(StorageSecurityError):
        storage.save("../escape.bin", payload)

    with pytest.raises(StorageSecurityError):
        storage.read("../../secret.txt")

    # Absolute path escaping base_dir prevention
    outside_path = str(tmp_path.parent / "escape_abs.bin")
    with pytest.raises(StorageSecurityError):
        storage.save(outside_path, payload)

    with pytest.raises(StorageSecurityError):
        storage.read(outside_path)

    # UNC path prevention
    with pytest.raises(StorageSecurityError):
        storage.read("//server/share/file.txt")

    with pytest.raises(StorageSecurityError):
        storage.read(r"\\server\share\file.txt")


# ---------------------------------------------------------------------------
# 2. Document Validator Tests
# ---------------------------------------------------------------------------

def test_validator_valid_pdf_and_images():
    pdf_bytes = create_dummy_pdf(pages=3)
    val_pdf = validate_uploaded_document("invoice.pdf", pdf_bytes)
    assert val_pdf.mime_type == "application/pdf"
    assert val_pdf.page_count == 3
    assert len(val_pdf.sha256) == 64

    png_bytes = create_dummy_image("PNG")
    val_png = validate_uploaded_document("site_ticket.png", png_bytes)
    assert val_png.mime_type == "image/png"
    assert val_png.page_count == 1

    jpg_bytes = create_dummy_image("JPEG")
    val_jpg = validate_uploaded_document("dn_photo.jpg", jpg_bytes)
    assert val_jpg.mime_type == "image/jpeg"
    assert val_jpg.page_count == 1


def test_validator_rejects_empty_and_oversized_files():
    with pytest.raises(CorruptDocumentError, match="empty"):
        validate_uploaded_document("empty.pdf", b"")

    huge_payload = b"%PDF-" + (b"0" * (20 * 1024 * 1024 + 10))
    with pytest.raises(FileTooLargeError, match="exceeds maximum allowed limit of 20 MB"):
        validate_uploaded_document("huge.pdf", huge_payload)


def test_validator_rejects_unsupported_media_types():
    with pytest.raises(UnsupportedMediaTypeError, match="Allowed formats: PDF, JPEG, PNG"):
        validate_uploaded_document("test.txt", b"plain text invoice data without magic bytes")


def test_validator_rejects_encrypted_pdf():
    enc_pdf = create_dummy_pdf(pages=1, password="secret_password_123")
    with pytest.raises(EncryptedDocumentError, match="Password-protected or encrypted PDFs are not accepted"):
        validate_uploaded_document("secret.pdf", enc_pdf)


def test_validator_rejects_pdf_exceeding_page_limit():
    multi_page_pdf = create_dummy_pdf(pages=51)
    with pytest.raises(PageLimitExceededError, match="exceeds the maximum limit of 50 pages"):
        validate_uploaded_document("large.pdf", multi_page_pdf)


def test_validator_rejects_corrupted_pdf_or_image():
    corrupted_pdf = b"%PDF-malformed-binary-garbage"
    with pytest.raises(CorruptDocumentError):
        validate_uploaded_document("corrupted.pdf", corrupted_pdf)

    corrupted_png = b"\x89PNG\r\n\x1a\ncorrupted-image-data"
    with pytest.raises(CorruptDocumentError):
        validate_uploaded_document("corrupted.png", corrupted_png)


# ---------------------------------------------------------------------------
# 3. Document API & Service Tests
# ---------------------------------------------------------------------------

@pytest.fixture
def app_client(tmp_path):
    """Test client configured with isolated storage directory and test database."""
    test_db_path = tmp_path / "test_m3.db"
    test_storage_path = tmp_path / "test_storage"
    test_storage_path.mkdir(parents=True, exist_ok=True)

    test_engine = create_engine(
        f"sqlite:///{test_db_path}",
        connect_args={"check_same_thread": False},
    )
    with test_engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys = ON;")

    Base.metadata.create_all(bind=test_engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    with TestingSessionLocal() as session:
        seed_database(session)

    settings = Settings(
        app_env="development",
        dev_identity_enabled=True,
        database_url=f"sqlite:///{test_db_path}",
        storage_dir=str(test_storage_path),
    )
    app = create_app(settings)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    test_storage = LocalStorage(base_dir=test_storage_path)

    def override_storage():
        return test_storage

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_document_storage] = override_storage

    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        yield client


def test_document_upload_success_and_metadata_retrieval(app_client):
    pdf_bytes = create_dummy_pdf(pages=2)
    files = {"file": ("synthetic_invoice_1.pdf", pdf_bytes, "application/pdf")}
    data = {"doc_type": "INVOICE"}

    resp = client_post = app_client.post(
        "/api/v1/cases/case-synth-01/documents",
        files=files,
        data=data,
        headers={"x-simulated-user": "usr-sim-eng"},
    )
    assert resp.status_code == 201
    payload = resp.json()
    assert payload["synthetic_data_only"] is True
    assert payload["reuse_warning"] is False
    doc_id = payload["document"]["id"]
    assert payload["document"]["page_count"] == 2
    assert payload["document"]["doc_type"] == "INVOICE"

    # Verify metadata endpoint
    meta_resp = app_client.get(f"/api/v1/documents/{doc_id}")
    assert meta_resp.status_code == 200
    assert meta_resp.json()["document"]["id"] == doc_id

    # Verify binary download content endpoint
    content_resp = app_client.get(f"/api/v1/documents/{doc_id}/content")
    assert content_resp.status_code == 200
    assert content_resp.content == pdf_bytes
    assert "synthetic_invoice_1.pdf" in content_resp.headers["Content-Disposition"]

    # Verify page info endpoint
    page_resp = app_client.get(f"/api/v1/documents/{doc_id}/pages/1")
    assert page_resp.status_code == 200
    assert page_resp.json()["page_number"] == 1
    assert page_resp.json()["total_pages"] == 2


def test_duplicate_upload_in_same_case_returns_409(app_client):
    pdf_bytes = create_dummy_pdf(pages=1)
    files = {"file": ("dn_ticket.pdf", pdf_bytes, "application/pdf")}
    data = {"doc_type": "DELIVERY_NOTE"}

    # Upload first time
    r1 = app_client.post("/api/v1/cases/case-synth-05/documents", files=files, data=data)
    assert r1.status_code == 201

    # Upload exact same content again to SAME case
    files2 = {"file": ("dn_ticket_copy.pdf", pdf_bytes, "application/pdf")}
    r2 = app_client.post("/api/v1/cases/case-synth-05/documents", files=files2, data=data)
    assert r2.status_code == 409
    assert "DUPLICATE_DOCUMENT_IN_CASE" in r2.json()["detail"]["code"]


def test_cross_case_duplicate_returns_201_with_reuse_warning(app_client):
    pdf_bytes = create_dummy_pdf(pages=1)
    files1 = {"file": ("dn_original.pdf", pdf_bytes, "application/pdf")}
    data = {"doc_type": "DELIVERY_NOTE"}

    # Upload to Case 1
    r1 = app_client.post("/api/v1/cases/case-synth-01/documents", files=files1, data=data)
    assert r1.status_code == 201
    assert r1.json()["reuse_warning"] is False

    # Upload exact same content to Case 5 (cross-case duplicate)
    files2 = {"file": ("dn_reused.pdf", pdf_bytes, "application/pdf")}
    r2 = app_client.post("/api/v1/cases/case-synth-05/documents", files=files2, data=data)
    assert r2.status_code == 201
    payload = r2.json()
    assert payload["reuse_warning"] is True
    assert payload["conflict_case_id"] == "case-synth-01"
    assert payload["conflict_case_ref"] == "VC-2026-00001"


def test_upload_to_nonexistent_case_returns_404(app_client):
    pdf_bytes = create_dummy_pdf(pages=1)
    files = {"file": ("dn.pdf", pdf_bytes, "application/pdf")}
    data = {"doc_type": "DELIVERY_NOTE"}

    resp = app_client.post("/api/v1/cases/case-does-not-exist/documents", files=files, data=data)
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "CASE_NOT_FOUND"


def test_soft_delete_and_replace_document(app_client):
    pdf_bytes_1 = create_dummy_pdf(pages=1)
    files1 = {"file": ("original_inv.pdf", pdf_bytes_1, "application/pdf")}
    data1 = {"doc_type": "INVOICE"}

    upload_resp = app_client.post("/api/v1/cases/case-synth-01/documents", files=files1, data=data1)
    doc_id = upload_resp.json()["document"]["id"]

    # Replace document
    pdf_bytes_2 = create_dummy_image("PNG")
    files2 = {"file": ("replaced_inv.png", pdf_bytes_2, "image/png")}
    data2 = {"doc_type": "INVOICE"}

    replace_resp = app_client.post(f"/api/v1/documents/{doc_id}/replace", files=files2, data=data2)
    assert replace_resp.status_code == 201
    new_doc_id = replace_resp.json()["new_document"]["id"]
    assert replace_resp.json()["superseded_document_id"] == doc_id

    # Old document should now be marked superseded and soft-deleted (404 on normal fetch)
    old_fetch = app_client.get(f"/api/v1/documents/{doc_id}")
    assert old_fetch.status_code == 404

    # New document is active
    new_fetch = app_client.get(f"/api/v1/documents/{new_doc_id}")
    assert new_fetch.status_code == 200

    # Soft delete new document
    del_resp = app_client.delete(f"/api/v1/documents/{new_doc_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["is_deleted"] is True

    # After deletion, 404 on fetch
    assert app_client.get(f"/api/v1/documents/{new_doc_id}").status_code == 404


# ---------------------------------------------------------------------------
# 4. Failure Simulation Tests: Atomicity & Safe Storage Cleanup
# ---------------------------------------------------------------------------

@pytest.fixture
def service_env(tmp_path):
    """Isolated database session and storage directory for service-level testing."""
    test_db_path = tmp_path / "test_svc.db"
    test_storage_path = tmp_path / "test_svc_storage"
    test_storage_path.mkdir(parents=True, exist_ok=True)

    engine = create_engine(
        f"sqlite:///{test_db_path}",
        connect_args={"check_same_thread": False},
    )
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys = ON;")

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()
    seed_database(session)

    storage = LocalStorage(base_dir=test_storage_path)
    service = DocumentService(session=session, storage=storage)

    try:
        yield service, session, storage
    finally:
        session.close()


def test_upload_db_failure_cleans_up_stored_file_and_rolls_back(service_env, monkeypatch):
    """Database failure after saving file cleans up stored file and leaves no DB records."""
    service, session, storage = service_env
    pdf_bytes = create_dummy_pdf(pages=1)

    # Monkeypatch session.flush to simulate a database failure during record insertion
    def failing_flush():
        raise RuntimeError("Simulated database failure during flush")

    monkeypatch.setattr(session, "flush", failing_flush)

    with pytest.raises(RuntimeError, match="Simulated database failure during flush"):
        service.upload_document(
            case_id="case-synth-01",
            filename="failed_upload.pdf",
            content=pdf_bytes,
            doc_type="INVOICE",
        )

    # Verify storage: no file was left orphaned
    stored_files = list(storage.base_dir.iterdir())
    assert len(stored_files) == 0

    # Verify database: no document record was persisted
    persisted_docs = session.scalars(
        select(DocumentOrm).where(DocumentOrm.original_filename == "failed_upload.pdf")
    ).all()
    assert len(persisted_docs) == 0

    # Verify audit: no upload audit event was persisted
    audit_events = session.scalars(
        select(AuditEventOrm).where(AuditEventOrm.action == "DOCUMENT_UPLOADED")
    ).all()
    assert len(audit_events) == 0


def test_replace_db_failure_cleans_up_new_file_and_preserves_old_doc(service_env, monkeypatch):
    """Database failure during replacement cleans up the new file and leaves the original document active."""
    service, session, storage = service_env

    # 1. Clean upload of initial document
    pdf_bytes_1 = create_dummy_pdf(pages=1)
    initial_res = service.upload_document(
        case_id="case-synth-01",
        filename="initial_doc.pdf",
        content=pdf_bytes_1,
        doc_type="INVOICE",
    )
    initial_doc_id = initial_res.document.id
    initial_storage_key = initial_res.document.storage_key
    assert storage.exists(initial_storage_key)

    # 2. Simulate database failure during the replacement commit
    original_commit = session.commit
    def failing_commit():
        raise RuntimeError("Simulated DB failure during replacement commit")

    monkeypatch.setattr(session, "commit", failing_commit)

    pdf_bytes_2 = create_dummy_image("PNG")
    with pytest.raises(RuntimeError, match="Simulated DB failure during replacement commit"):
        service.replace_document(
            document_id=initial_doc_id,
            new_filename="failed_replacement.png",
            new_content=pdf_bytes_2,
            new_doc_type="INVOICE",
        )

    # Restore commit for inspection queries
    monkeypatch.setattr(session, "commit", original_commit)

    # Verify original document remains completely active and un-superseded
    old_doc = session.get(DocumentOrm, initial_doc_id)
    assert old_doc is not None
    assert old_doc.is_deleted is False
    assert old_doc.superseded_by_id is None

    # Verify original file in storage is preserved intact
    assert storage.exists(initial_storage_key)

    # Verify no new replacement file was left orphaned in storage
    all_files = [f.name for f in storage.base_dir.iterdir()]
    assert all_files == [initial_storage_key]

    # Verify no DOCUMENT_SUPERSEDED audit event was committed
    superseded_events = session.scalars(
        select(AuditEventOrm).where(AuditEventOrm.action == "DOCUMENT_SUPERSEDED")
    ).all()
    assert len(superseded_events) == 0


def test_upload_filesystem_failure_leaves_no_database_records(service_env, monkeypatch):
    """Filesystem failure during upload raises error and touches zero database records."""
    service, session, storage = service_env
    pdf_bytes = create_dummy_pdf(pages=1)

    def failing_save(storage_key, data):
        raise OSError("Simulated disk write failure")

    monkeypatch.setattr(storage, "save", failing_save)

    with pytest.raises(OSError, match="Simulated disk write failure"):
        service.upload_document(
            case_id="case-synth-01",
            filename="io_error.pdf",
            content=pdf_bytes,
            doc_type="INVOICE",
        )

    # Verify no DB records or files created
    assert session.scalars(select(DocumentOrm).where(DocumentOrm.original_filename == "io_error.pdf")).first() is None
    assert len(list(storage.base_dir.iterdir())) == 0


def test_replace_ambiguous_commit_preserves_stored_file_if_record_committed(service_env, monkeypatch):
    """If an exception occurs during/after commit but the DB record was committed, do NOT delete the file."""
    service, session, storage = service_env

    # 1. Upload initial document
    initial_res = service.upload_document(
        case_id="case-synth-01",
        filename="initial_doc.pdf",
        content=create_dummy_pdf(pages=1),
        doc_type="INVOICE",
    )
    initial_doc_id = initial_res.document.id

    # 2. Simulate ambiguous commit: the real commit completes, but post-commit hook raises exception
    real_commit = session.commit
    def ambiguous_commit():
        real_commit()  # Changes are committed to SQLite
        raise RuntimeError("Simulated post-commit failure / ambiguous commit")

    monkeypatch.setattr(session, "commit", ambiguous_commit)

    png_bytes = create_dummy_image("PNG")
    with pytest.raises(RuntimeError, match="Simulated post-commit failure / ambiguous commit"):
        service.replace_document(
            document_id=initial_doc_id,
            new_filename="replacement_unusual_ext.custom",  # Test extension normalization
            new_content=png_bytes,
            new_doc_type="INVOICE",
        )

    # Restore commit
    monkeypatch.setattr(session, "commit", real_commit)

    # Verify that the replacement document was committed in the DB
    old_doc = session.get(DocumentOrm, initial_doc_id)
    assert old_doc.is_deleted is True
    assert old_doc.superseded_by_id is not None
    new_doc_id = old_doc.superseded_by_id
    new_doc = session.get(DocumentOrm, new_doc_id)
    assert new_doc is not None
    assert new_doc.storage_key.endswith(".png")  # Extension derived from MIME type, not .custom

    # Verify that the file in storage was NOT deleted because the record was committed!
    assert storage.exists(new_doc.storage_key) is True


def test_seeded_synthetic_document_preview_and_controlled_error_on_missing(app_client):
    """Regression test: seeded synthetic documents can be retrieved when storage file exists,
    and missing storage files return controlled 404 STORAGE_FILE_MISSING error without raw exceptions.
    """
    storage = app_client.app.dependency_overrides[get_document_storage]()

    # 1. When storage file is present (created during lifespan), preview endpoint returns 200 with PDF
    resp_success = app_client.get("/api/v1/documents/doc-c2-dn5110/content")
    assert resp_success.status_code == 200
    assert resp_success.headers["Content-Type"] == "application/pdf"
    assert 'filename="DN-5110.pdf"' in resp_success.headers["Content-Disposition"]
    assert resp_success.content.startswith(b"%PDF")

    # 2. If storage file is missing from disk, requesting document content returns controlled 404 error
    dn_file = storage.base_dir / "synthetic_dn_5110.pdf"
    if dn_file.exists():
        dn_file.unlink()

    resp_missing = app_client.get("/api/v1/documents/doc-c2-dn5110/content")
    assert resp_missing.status_code == 404
    error_payload = resp_missing.json()
    assert error_payload["detail"]["code"] == "STORAGE_FILE_MISSING"
    assert "synthetic_dn_5110.pdf" in error_payload["detail"]["message"]

    # 3. Call ensure_synthetic_storage_files to restore missing file idempotently
    created = ensure_synthetic_storage_files(storage.base_dir)
    assert "synthetic_dn_5110.pdf" in created

    # 4. Verify preview endpoint succeeds again once file is restored
    resp_restored = app_client.get("/api/v1/documents/doc-c2-dn5110/content")
    assert resp_restored.status_code == 200
    assert resp_restored.content.startswith(b"%PDF")

    # 5. Also verify another seeded synthetic document (e.g. invoice INV-9042)
    resp_inv = app_client.get("/api/v1/documents/doc-c2-inv/content")
    assert resp_inv.status_code == 200
    assert resp_inv.headers["Content-Type"] == "application/pdf"
    assert 'filename="INV-9042.pdf"' in resp_inv.headers["Content-Disposition"]
    assert resp_inv.content.startswith(b"%PDF")


def test_synthetic_pdf_ascii_safe_glyphs():
    """Verify synthetic PDF generation uses ASCII-safe warning banner and units (no em-dash or superscript 3)."""
    for fname, meta in SYNTHETIC_DOCUMENT_FILES.items():
        for _label, val in meta.get("details", []):
            assert "—" not in val, f"Unicode em-dash found in {fname}: {val}"
            assert "³" not in val, f"Unicode superscript 3 found in {fname}: {val}"
            if "m3" in val:
                assert "m³" not in val

    pdf_bytes = generate_synthetic_pdf_bytes(
        title="TAX INVOICE INV-9042",
        doc_ref="INV-9042",
        case_ref="VC-2026-00002",
        supplier="Gulf ReadyMix Concrete LLC (Synthetic)",
        details=[("Invoiced Qty:", "24.000 m3")],
    )
    assert pdf_bytes.startswith(b"%PDF")
    # Verify the byte stream does not contain UTF-8 encoded em-dash or superscript 3
    assert "—".encode("utf-8") not in pdf_bytes
    assert "³".encode("utf-8") not in pdf_bytes

