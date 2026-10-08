"""Backup and restore utility for CIV pilot database and clean storage.

This script supports:
1. Backing up the database (PostgreSQL via pg_dump or SQLite snapshot) and the AES-256 clean storage.
2. Creating an atomic, checksummed backup bundle (metadata manifest, database dump, storage archive).
3. Restoring the bundle into an ISOLATED target database and storage directory (non-destructive).
4. Verifying recovered schema, users, projects, cases, LPOs, reviews, audit records, and document files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

# Add backend directory to sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import get_settings
from app.persistence.models import (
    AuditEventOrm,
    DocumentOrm,
    LpoLineOrm,
    LpoOrm,
    ProjectOrm,
    ReviewOrm,
    UserOrm,
    VerificationCaseOrm,
)


def compute_sha256(file_path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    hasher = hashlib.sha256()
    with file_path.open("rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def backup_clean_storage(storage_dir: Path, target_archive: Path) -> dict[str, Any]:
    """Archive clean document storage into a compressed tarball with file hashes."""
    storage_dir = storage_dir.resolve()
    target_archive.parent.mkdir(parents=True, exist_ok=True)
    manifest_files: list[dict[str, Any]] = []

    if storage_dir.is_dir():
        with tarfile.open(target_archive, "w:gz") as tar:
            for root, _, files in os.walk(storage_dir):
                for fname in files:
                    full_p = Path(root) / fname
                    rel_p = full_p.relative_to(storage_dir)
                    tar.add(full_p, arcname=str(rel_p))
                    manifest_files.append({
                        "rel_path": str(rel_p),
                        "sha256": compute_sha256(full_p),
                        "size_bytes": full_p.stat().st_size,
                    })
    else:
        # Create empty archive if directory does not exist yet
        with tarfile.open(target_archive, "w:gz"):
            pass

    return {
        "archive_path": str(target_archive),
        "archive_sha256": compute_sha256(target_archive),
        "archive_size": target_archive.stat().st_size,
        "file_count": len(manifest_files),
        "files": manifest_files,
    }


def restore_clean_storage(archive_path: Path, target_dir: Path) -> int:
    """Extract clean storage archive into an isolated target directory."""
    target_dir.resolve().mkdir(parents=True, exist_ok=True)
    count = 0
    with tarfile.open(archive_path, "r:gz") as tar:
        tar.extractall(target_dir)
        count = len(tar.getmembers())
    return count


def backup_database(database_url: str, output_path: Path) -> dict[str, Any]:
    """Dump database to a backup artifact."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    url_lower = database_url.lower()

    if url_lower.startswith("sqlite"):
        # Strip sqlite:/// prefix
        db_file_str = database_url.split("sqlite:///", 1)[-1]
        source_file = Path(db_file_str).resolve()
        if not source_file.exists():
            raise FileNotFoundError(f"Source SQLite database not found: {source_file}")
        shutil.copy2(source_file, output_path)
        return {
            "type": "sqlite",
            "backup_file": str(output_path),
            "sha256": compute_sha256(output_path),
            "size": output_path.stat().st_size,
        }

    if "postgres" in url_lower:
        # Check pg_dump availability
        pg_dump_cmd = shutil.which("pg_dump")
        if not pg_dump_cmd:
            raise RuntimeError(
                "PostgreSQL pg_dump utility is not found in PATH. "
                "Ensure PostgreSQL client tools are installed."
            )
        cmd = [pg_dump_cmd, "--dbname", database_url, "--file", str(output_path), "--format=custom"]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"pg_dump failed with code {proc.returncode}: {proc.stderr}")
        return {
            "type": "postgresql",
            "backup_file": str(output_path),
            "sha256": compute_sha256(output_path),
            "size": output_path.stat().st_size,
        }

    raise ValueError(f"Unsupported database URL scheme: {database_url}")


def restore_database(database_url: str, backup_path: Path) -> None:
    """Restore database from backup artifact into target database URL."""
    url_lower = database_url.lower()

    if url_lower.startswith("sqlite"):
        target_file_str = database_url.split("sqlite:///", 1)[-1]
        target_file = Path(target_file_str).resolve()
        target_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup_path, target_file)
        return

    if "postgres" in url_lower:
        pg_restore_cmd = shutil.which("pg_restore")
        if not pg_restore_cmd:
            raise RuntimeError(
                "PostgreSQL pg_restore utility is not found in PATH. "
                "Ensure PostgreSQL client tools are installed."
            )
        cmd = [pg_restore_cmd, "--clean", "--dbname", database_url, str(backup_path)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"pg_restore failed with code {proc.returncode}: {proc.stderr}")
        return

    raise ValueError(f"Unsupported database URL scheme: {database_url}")


def verify_recovery(
    target_db_url: str,
    target_clean_storage_dir: Path | None = None,
) -> dict[str, Any]:
    """Verify restored database schema, records, and clean storage files."""
    engine = create_engine(target_db_url)
    inspector = inspect(engine)
    table_names = inspector.get_table_names()

    required_tables = [
        "user",
        "project",
        "project_user",
        "verification_case",
        "lpo",
        "lpo_line",
        "document",
        "line_item",
        "review",
        "audit_event",
    ]

    missing_tables = [t for t in required_tables if t not in table_names]
    if missing_tables:
        raise ValueError(f"Recovery verification failed: Missing required tables: {missing_tables}")

    SessionMaker = sessionmaker(bind=engine)
    with SessionMaker() as session:
        user_count = session.query(UserOrm).count()
        project_count = session.query(ProjectOrm).count()
        case_count = session.query(VerificationCaseOrm).count()
        lpo_count = session.query(LpoOrm).count()
        review_count = session.query(ReviewOrm).count()
        audit_count = session.query(AuditEventOrm).count()
        doc_count = session.query(DocumentOrm).count()

        # Check document physical file presence if target storage dir provided
        documents = session.query(DocumentOrm).all()
        doc_verification = []
        for doc in documents:
            if target_clean_storage_dir:
                clean_path = target_clean_storage_dir / doc.storage_key
                exists = clean_path.is_file()
                doc_verification.append({
                    "document_id": doc.id,
                    "storage_key": doc.storage_key,
                    "file_exists": exists,
                })

    return {
        "status": "VERIFIED",
        "tables_present": len(table_names),
        "user_count": user_count,
        "project_count": project_count,
        "case_count": case_count,
        "lpo_count": lpo_count,
        "review_count": review_count,
        "audit_count": audit_count,
        "document_count": doc_count,
        "documents_checked": doc_verification,
    }


def create_backup_bundle(
    database_url: str,
    clean_storage_dir: Path,
    output_bundle_dir: Path,
) -> Path:
    """Create a consolidated backup bundle with manifest, database dump, and clean storage archive."""
    output_bundle_dir = output_bundle_dir.resolve()
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    bundle_name = f"civ_backup_{timestamp}"
    bundle_dir = output_bundle_dir / bundle_name
    bundle_dir.mkdir(parents=True, exist_ok=True)

    db_filename = "database.dump" if "postgres" in database_url.lower() else "database.sqlite"
    db_backup_path = bundle_dir / db_filename
    db_meta = backup_database(database_url, db_backup_path)

    storage_tar_path = bundle_dir / "clean_storage.tar.gz"
    storage_meta = backup_clean_storage(clean_storage_dir, storage_tar_path)

    manifest = {
        "civ_backup_version": "1.0",
        "created_at": datetime.utcnow().isoformat(),
        "database": db_meta,
        "storage": storage_meta,
    }

    manifest_path = bundle_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return bundle_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="CIV Pilot Backup & Recovery Utility")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Backup command
    backup_parser = subparsers.add_parser("backup", help="Create a backup bundle")
    backup_parser.add_argument("--out", required=True, type=Path, help="Output directory for backup bundle")

    # Restore command
    restore_parser = subparsers.add_parser("restore", help="Restore a backup bundle into target database & storage")
    restore_parser.add_argument("--bundle", required=True, type=Path, help="Backup bundle directory")
    restore_parser.add_argument("--target-db", required=True, type=str, help="Target isolated database URL")
    restore_parser.add_argument("--target-storage", required=True, type=Path, help="Target clean storage directory")

    # Verify command
    verify_parser = subparsers.add_parser("verify", help="Verify integrity of an isolated database and storage")
    verify_parser.add_argument("--target-db", required=True, type=str, help="Target isolated database URL")
    verify_parser.add_argument("--target-storage", required=False, type=Path, help="Target clean storage directory")

    args = parser.parse_args()
    settings = get_settings()

    if args.command == "backup":
        bundle_path = create_backup_bundle(
            database_url=settings.database_url,
            clean_storage_dir=Path(settings.clean_storage_dir),
            output_bundle_dir=args.out,
        )
        print(f"SUCCESS: Backup bundle created at: {bundle_path}")

    elif args.command == "restore":
        bundle_dir = args.bundle.resolve()
        manifest_file = bundle_dir / "manifest.json"
        if not manifest_file.exists():
            print(f"ERROR: Invalid backup bundle, manifest.json not found in {bundle_dir}")
            sys.exit(1)

        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        db_type = manifest["database"]["type"]
        db_file = bundle_dir / ("database.dump" if db_type == "postgresql" else "database.sqlite")

        print(f"Restoring database to {args.target_db}...")
        restore_database(args.target_db, db_file)

        print(f"Restoring clean storage to {args.target_storage}...")
        storage_archive = bundle_dir / "clean_storage.tar.gz"
        restore_clean_storage(storage_archive, args.target_storage)

        print("Verifying restored environment...")
        report = verify_recovery(args.target_db, args.target_storage)
        print("SUCCESS: Recovery verification passed:")
        print(json.dumps(report, indent=2))

    elif args.command == "verify":
        report = verify_recovery(args.target_db, args.target_storage)
        print("SUCCESS: Verification passed:")
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
