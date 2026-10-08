# Construction Invoice Verification (CIV)

A deterministic, multi-way evidence-chain reconciliation engine and review system for construction material procurement, site deliveries, and contractor billing.

---

## Overview & Problem Statement

In commercial construction and civil engineering projects, material procurement accounts for a substantial portion of project cash flow. Invoicing for bulk materials (ready-mix concrete, reinforcing steel, aggregates, masonry blocks, and cement) is notoriously vulnerable to discrepancies:
- **Quantity Mismatches:** Invoiced amounts exceeding site-verified received quantities.
- **Delivery Note Reuse:** The same delivery note ticket cited across multiple supplier invoices.
- **Ghost Deliveries & Missing Evidence:** Invoices submitted without corresponding physical site tickets, storekeeper endorsements, or site engineer verifications.
- **Uncapped Procurement:** Invoices billed without approved Local Purchase Orders (LPOs) or exceeding contractual purchase order monetary caps.
- **Calculation Drift & Premature Disbursements:** Erroneous tax/rounding calculations or unverified automated payments.

**Construction Invoice Verification (CIV)** is an engineering pilot and prototype designed to solve this reconciliation problem deterministically. CIV enforces a strict, mathematical evidence chain across procurement documents and site records before any commercial review decision can be recorded.

---

## Core Philosophy: Deterministic Rules & Mandatory Human Review

CIV is built on two core principles:

1. **Zero Silent Automation / No Auto-Pay:**  
   CIV never approves invoices automatically, never disburses funds, and never connects directly to banking or disbursement rails. Every payment approval requires an explicit, authenticated, human review decision by an authorized reviewer.
2. **Deterministic Domain Rules:**  
   Reconciliation rules (quantities, rates, caps, unit compatibility, evidence linking) are evaluated with strict decimal arithmetic (zero tolerance for quantity overages) and fail-closed state machines.

---

## Evidence Chain Reconciliation Workflow

The system models the physical construction procurement lifecycle:

```
┌─────────────────┐       ┌──────────────────────┐       ┌──────────────────────┐
│  Contractor /   │  ───> │  Physical Delivery   │  ───> │   Site Receipt &     │
│   Project LPO   │       │   (Supplier Ticket)  │       │  Inspection Protocol │
│ (Cap, Rate, UOM)│       │  (DN-01, Delivered)  │       │  (Accepted vs Rej.)  │
└─────────────────┘       └──────────────────────┘       └──────────────────────┘
         │                           │                               │
         └───────────────────────────┼───────────────────────────────┘
                                     │
                                     v
                        ┌────────────────────────┐
                        │   Supplier Invoice     │
                        │ (Invoiced Qty & Total) │
                        └────────────────────────┘
                                     │
                                     v
                        ┌────────────────────────┐
                        │   CIV Matching Engine  │
                        │ (Deterministic Rules)  │
                        └────────────────────────┘
                                     │
                                     v
                        ┌────────────────────────┐
                        │  Human Review Decision │
                        │ (Accept / Query / Hold)│
                        └────────────────────────┘
```

### Complete Evidence Chain:
1. **LPO (Local Purchase Order):** Establishes authorized project scope, supplier identity, agreed unit rates, and contractual quantity/monetary caps.
2. **Delivery Note (DN):** Records supplier dispatch details and gross/tare delivery quantities.
3. **Site Acceptance:** Captures physical receipt by the site storekeeper and verification by the site engineer, explicitly recording any rejected quantities (e.g., slump test failure, batch contamination).
4. **Supplier Invoice:** Submitted for commercial settlement against the matched delivery tickets.
5. **Human Review:** An authorized Commercial Project Manager or Quantity Surveyor reviews the reconciliation findings and records an auditable decision (Approved, On Hold / Queried, or Rejected).

---

## Key Verification Rules

CIV enforces numbered, auditable business rules:

| Rule Code | Domain Policy | Enforcement Mechanism |
|---|---|---|
| **D1** | **Quantity Zero Tolerance** | Exact decimal comparison between invoiced quantity and accepted delivered quantity. Zero tolerance; never rounded or approximated. |
| **D2** | **Delivered Quantity Basis** | Reconciliation is strictly calculated using *accepted* delivered quantity (`delivered_qty - rejected_qty`), taking into account site rejection evidence. |
| **D3 / C1** | **Delivery Note Reuse Prevention** | A delivery note can only be allocated to one commercial case. Reuse across multiple invoices is permanently flagged as a critical audit finding. |
| **D4** | **Mandatory LPO / Cap Tracking** | An approved LPO is required unless explicitly waived with a documented reason code. Cumulative consumption cannot exceed LPO quantity or monetary caps. |
| **D5 / C4** | **Tax & Financial Precision** | Financial values are calculated using fixed 2-decimal-place fils precision (`ROUND_HALF_UP`). Automated VAT validation remains gated pending tax authority integration. |
| **D6** | **Separation of Duties (SoD)** | Case creators and document uploaders cannot record review decisions on their own cases. Review decisions require authorized reviewer credentials (`can_review=True`). |
| **F8** | **Missing Evidence Protection** | Invoices lacking matching delivery notes, physical signatures, or site confirmations are blocked from approval. |

---

## System Architecture

The application is structured into decoupled frontend, backend, and security layers:

```
[ Browser / Single-Page Application ]
                 │  HTTPS (TLS 1.3)
                 v
   [ Caddy Reverse Proxy :8443 ]
                 │
                 │  Reverse Proxy (/api/v1 -> :8000)
                 v
   [ FastAPI Application Service :8000 ]
     ├── Domain Verification Engine (Deterministic Rules)
     ├── JWT Authentication & Project-Scoped RBAC
     ├── Separation of Duties (SoD) Enforcer
     ├── AES-256-GCM Storage Encryption Service
     └── ClamAV Anti-Malware Streaming Client
                 │
        ┌────────┴────────┐
        v                 v
[ PostgreSQL 16 ]    [ ClamAV Daemon ]
  (ACID Storage &      (In-Memory Stream
   Append-Only Audit)   Inspection :3310)
```

### Component Stack
- **Backend:** Python 3.10+, FastAPI, SQLAlchemy 2.0, Alembic, Pydantic, Uvicorn.
- **Frontend:** React 19, TypeScript, Vite, Tailwind CSS, Lucide Icons.
- **Database:** PostgreSQL 16 (production/pilot container) / SQLite (isolated test harness).
- **Anti-Malware:** ClamAV daemon (`clamd`) running in an isolated container.
- **Reverse Proxy / TLS:** Caddy 2 with automated localhost TLS and secure HTTP response headers (HSTS, CSP, X-Frame-Options, X-Content-Type-Options).
- **Storage:** AES-256-GCM encrypted local partitioned document repository (Clean / Quarantine partitions).

---

## Security Architecture

1. **Loopback-Only Service Bindings:**  
   PostgreSQL (`127.0.0.1:5432`) and ClamAV (`127.0.0.1:3310`) bind exclusively to the local loopback interface. Public exposure (`0.0.0.0`) is prohibited.
2. **Encrypted Document Storage:**  
   Uploaded document files are encrypted at rest using authenticated AES-256-GCM encryption with 96-bit random initialization vectors (IVs).
3. **Malware Scanning (Fail-Closed):**  
   All uploaded PDFs and images are streamed to the ClamAV daemon prior to clean storage. The scanner fails closed: if ClamAV is unreachable or detects a signature, the upload is quarantined and rejected.
4. **PDF Sanitization:**  
   Uploaded PDF documents are inspected for embedded JavaScript and launch actions (`/JavaScript`, `/JS`, `/Launch`), preventing malicious payloads.
5. **Project-Scoped Authorization & RBAC:**  
   Users only have visibility and access to cases associated with projects they are explicitly assigned to. Cross-project data access returns `403 Forbidden`.
6. **Append-Only Audit Trail:**  
   Audit events are recorded in an append-only audit trail with actor IDs, timestamps, and entity references for complete lifecycle traceability.

---

## Testing & Quality Assurance

The codebase includes comprehensive test suites covering domain rules, security, persistence, and workflow regressions:

```bash
# Run backend pilot & security hardening tests
cd backend
pytest tests/test_m4a_pilot.py tests/test_m4b_hardening.py -v

# Run complete backend test suite
pytest tests/ -v

# Run frontend test suite
cd ../frontend
npm test -- --run

# Run frontend TypeScript build
npm run build
```

### Test Coverage Highlights:
- **Unit & Domain Engine:** Verification rule correctness, edge-case math, and unit conversions.
- **Security Hardening:** AES-256-GCM encryption/decryption, PDF script detection, malware upload rejection (EICAR standard string), database session revocation.
- **Separation of Duties (SoD):** Verification that uploaders cannot self-approve invoices.
- **Multi-Role Scenarios:** Isolated Site Engineers, Quantity Surveyors, and Commercial Reviewers across distinct projects.

---

## Synthetic Data Disclaimer

All data, vendor names, tax registration numbers (TRNs), invoice numbers, and project titles contained in this repository are **strictly synthetic and fictitious**:
- Example entities (e.g., *Emirates Cement Factory LLC (Synthetic)*, *Gulf ReadyMix Concrete LLC (Synthetic)*) are fabricated for testing and demonstration purposes only.
- TRNs are synthetic placeholders (e.g., `100123456700003`).
- All document templates and PDFs are programmatically generated test artifacts containing prominent synthetic watermarks.
- **Zero real commercial documents or private information are stored in this repository.**

---

## Current Project Status & Portfolio Scope

> **Project Classification:** Engineering Prototype / Controlled Pilot System.

### Current Implementation Scope:
- [x] Deterministic multi-way evidence-chain reconciliation engine (LPO, Delivery Notes, Site Acceptance, Invoices).
- [x] Separation of duties and authenticated role-based review workflows.
- [x] Project-scoped tenancy and access control.
- [x] Secure document upload with ClamAV virus scanning and AES-256-GCM encryption.
- [x] Append-only audit logging and database persistence (PostgreSQL 16).
- [x] TLS reverse proxy architecture with Caddy.
- [x] React single-page review dashboard and case viewer.

### Explicit Non-Scope / Future Roadmap:
- **No Automated Approval or Payment:** CIV deliberately does not disburse funds or approve payments automatically.
- **No Production OCR / LLM Ingestion:** Extraction currently operates on verified structured document payloads and synthetic metadata. Native multimodal OCR/LLM extraction is planned for future milestones.
- **No Direct ERP / Accounting Integration:** Invoicing exports currently output structured review decision records for manual or batch ERP import. Direct SAP/Oracle ERP connectors are future roadmap items.

---

## Local Development & Setup

### Prerequisites
- Python 3.10+
- Node.js 18+ and npm
- Docker Desktop (for PostgreSQL 16 and ClamAV containers)
- Caddy 2 (for TLS reverse proxy testing)

### 1. Infrastructure Services (Docker)
```bash
# Start PostgreSQL and ClamAV daemon containers
docker compose -f deploy/docker-compose.pilot.yml up -d
```

### 2. Backend Setup
```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Or on Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Configure environment from template
cp .env.example .env

# Run database migrations
alembic upgrade head

# Start FastAPI development server
uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

### 3. Frontend Setup
```bash
cd frontend
npm install
npm run dev
```

### 4. Reverse Proxy Gateway (Optional for HTTPS)
```bash
caddy run --config deploy/Caddyfile
# Application available at https://localhost:8443
```

---

## License

This project is licensed under the Apache 2.0 License. See [LICENSE](LICENSE) for details.
