# Construction Invoice Verification (CIV)

> **A deterministic, multi-way evidence-chain reconciliation engine and review workspace for construction material procurement, site deliveries, and contractor billing.**

---

## 1. Prototype Disclaimer

> **Notice:** Construction Invoice Verification (CIV) is an engineering portfolio prototype developed to demonstrate full-stack software architecture, AI-assisted document intake, and deterministic domain verification.
> - **Non-Production Status:** This application is **not** a commercially deployed system, is not certified for commercial accounting compliance, and does **not** connect to live banking, automated clearing house (ACH), or UAE Wages Protection System (WPS) payment rails.
> - **Fictional & Synthetic Entities:** All company names (e.g., *Atlas Orion ReadyMix LLC (Fictional Demo)*, *Vulcan Apex Rebar Fabrication LLC (Fictional Demo)*), project names (e.g., *Nova Meridian Residences - Tower 1 (Fictional Demo)*), Tax Registration Numbers (TRNs), and document PDFs are **strictly fictional and synthetic**. Zero real commercial documents, confidential corporate records, or personal data are stored in this repository.

---

## 2. Key Features

- **Multimodal AI Intake with Untrusted Quarantine:** Ingests supplier invoices and site delivery tickets using Google Gemini multimodal extraction into structured Pydantic schemas, quarantining all extracted fields until human review.
- **Pure Deterministic Verification Engine:** Evaluates 22 domain verification rules using exact Python `Decimal` arithmetic, zero quantity tolerance, and contract rate reconciliation.
- **Human-in-the-Loop Review Workspace:** Side-by-side interactive document and field review interface in React 19, allowing Quantity Surveyors to visually inspect, edit, and confirm extracted values.
- **Three-Way Reconciliation & LPO Cap Tracking:** Reconciles invoice line items against site delivery tickets and Local Purchase Order (LPO) contracts, enforcing authorized quantity ceilings.
- **Cross-Case Delivery Note Deduplication:** Prevents double-billing of delivery tickets across multiple invoices via document SHA-256 cryptographic hashes and normalized reference indexing.
- **Role-Based Access Control & Separation of Duties:** JWT authentication with project-scoped roles (`QS`, `ENGINEER`, `REVIEWER`, `ADMIN`). Enforces that case creators and document uploaders cannot self-approve invoices.
- **Tamper-Evident Append-Only Audit Trail:** Logs every field edit, revision reason, verification execution, and sign-off decision in an immutable PostgreSQL audit ledger.
- **Encrypted Document Storage at Rest:** Encrypts uploaded documents using AES-256-GCM authenticated encryption, paired with PDF malicious active-content scanning and ClamAV streaming protocol integration.

---

## 3. Business Problem & Motivation

In commercial civil engineering and building construction, materials procurement (ready-mix concrete, reinforcing steel, aggregates, and masonry blocks) represents a major portion of direct project expenditure. Under standard contracting practices (such as FIDIC conditions of subcontract and regional commercial codes), suppliers submit monthly consolidated tax invoices claiming payment for materials delivered to the site.

However, the physical reality of the construction site diverges sharply from the commercial office:
- **Dispatched vs. Accepted Delivered Quantities:** Batching plants bill gross dispatched quantities. On site, material is frequently rejected or reduced due to slump test failures, transit delays, offloading damage, or out-of-spec rebar grades. These rejections are hand-annotated on physical delivery tickets, but supplier invoices routinely claim 100% of the dispatched volume.
- **Delivery Note Reuse:** Without centralized cross-case indexing, delivery tickets can be inadvertently or intentionally resubmitted across multiple monthly progress claims or separate project contracts.
- **Missing Delivery Evidence:** Invoices are often submitted for lump-sum or call-off line items where site delivery tickets were lost, unsigned, or never generated.
- **Contractual Rate Drift & Cap Exceedance:** Invoices may subtly drift from unit rates agreed in Local Purchase Orders (LPOs) or exceed contractual purchase order quantity caps.

Manually cross-checking hundreds of paper delivery tickets against invoice line items is slow, fatiguing, and error-prone for project Quantity Surveyors (QS). CIV addresses this operational challenge by providing an auditable, hybrid verification platform that automates intake while keeping commercial decision authority strictly with human reviewers.

---

## 4. Three Showcase Scenarios

The system includes three pre-seeded showcase cases backed by synthetic PDF documents in the database (`civ_pilot`):

### Scenario 1: Clean Match (`SHOWCASE-CONC-01`)
- **Fictional Supplier:** Atlas Orion ReadyMix LLC (Fictional Demo)
- **Fictional Project:** Nova Meridian Residences - Tower 1 (Fictional Demo)
- **Invoiced Claim:** 36.00 m³ ReadyMix Concrete C40/20 @ AED 240.00/m³ = AED 8,640.00 (Document `INV-2026-CONC-001.pdf`).
- **Delivery Evidence:** Delivery note `DN-2026-CONC-081.pdf` confirming 36.00 m³ delivered and accepted on site.
- **Contractual Baseline:** LPO requirement waived under valid framework call-off (`LPO_001: INFO`).
- **What the Engine Detects:** Evaluates exact quantity match (`QTY_003: MATCH`), contractual framework waiver, and gates automated VAT (`VAT_UAE_000: INFO`). Overall run summary: **MATCH**.
- **Human Reviewer Action:** The commercial reviewer inspects the clean match findings and records a formal commercial sign-off approval.

### Scenario 2: Quantity Overbilling Discrepancy (`SHOWCASE-STEEL-02`)
- **Fictional Supplier:** Vulcan Apex Rebar Fabrication LLC (Fictional Demo)
- **Fictional Project:** Nova Meridian Residences - Tower 1 (Fictional Demo)
- **Invoiced Claim:** 20.00 tonnes High Tensile Rebar 16mm @ AED 3,100.00/t = AED 62,000.00 (Document `INV-2026-STEEL-002.pdf`).
- **Delivery Evidence:** Delivery note `DN-2026-STEEL-412.pdf` records that only 15.00 tonnes were accepted on site due to offloading damage.
- **What the Engine Detects:** Identifies the exact +5.00 tonne quantity discrepancy (`QTY_004: CRITICAL MISMATCH`). Calculates the unearned billing overstatement of **AED 15,500.00**.
- **Human Reviewer Action:** Reviewer sign-off is blocked until the discrepancy is dispositioned. The commercial reviewer records a dispute or deductions notice against the invoice.

### Scenario 3: Missing Delivery Evidence (`SHOWCASE-EVID-03`)
- **Fictional Supplier:** Vulcan Apex Rebar Fabrication LLC (Fictional Demo)
- **Fictional Project:** Nova Meridian Residences - Tower 1 (Fictional Demo)
- **Invoiced Claim:** 8.00 tonnes High Tensile Rebar 16mm @ AED 3,250.00/t = AED 26,000.00 (Document `INV-2026-MISS-003.pdf`), claiming AED 26,000.00.
- **Delivery Evidence:** Zero delivery notes attached.
- **What the Engine Detects:** Flags critical completeness violations (`COMP_002: CRITICAL` and `QTY_001: CRITICAL MISSING_EVIDENCE`), identifying an unverified commercial claim.
- **Human Reviewer Action:** The reviewer places the invoice on hold (`ON_HOLD_QUERIED`), notifying the vendor to supply certified site tickets before commercial assessment.

---

## 5. Architecture & Data Flow

```mermaid
flowchart TD
    subgraph Client ["Frontend Client (Browser)"]
        UI["React 19 + TypeScript SPA"]
        ReviewDrawer["Side-by-Side Field Review Workspace"]
    end

    subgraph API ["Application Tier (FastAPI :8000)"]
        Gateway["REST API Gateway (Bearer JWT)"]
        DocService["Document Storage Service"]
        ExtService["AI Extraction Service"]
        Engine["Pure Verification Engine (verify_case)"]
        Audit["Append-Only Audit Service"]
    end

    subgraph AI ["AI Intake Service"]
        GeminiAPI["Google Gemini 3.8 Flash (google-genai SDK)"]
        PyPDF["pypdf Text Fallback"]
    end

    subgraph Data ["Data & Storage Tier"]
        DB[("PostgreSQL 16 (civ_pilot)")]
        Vault["Encrypted Storage (AES-256-GCM)"]
    end

    UI -->|HTTPS / REST| Gateway
    Gateway --> DocService
    Gateway --> ExtService
    Gateway --> Engine
    Gateway --> Audit

    DocService --> Vault
    DocService --> DB
    Audit --> DB

    ExtService --> GeminiAPI
    ExtService --> PyPDF
    ExtService -->|Quarantined Fields| DB

    ReviewDrawer -->|Human Confirmation| Gateway
    Engine -->|Read Confirmed Data| DB
    Engine -->|Deterministic Findings| Gateway
```

---

## 6. Technology Stack

| Layer | Technology | Version | Purpose |
| :--- | :--- | :--- | :--- |
| **Backend Framework** | FastAPI | 0.142.2 | REST API gateway, OpenAPI contracts, asynchronous request handling. |
| **Data Validation** | Pydantic (v2) | 2.13.5 | Compile-time and runtime serialization, extraction schemas. |
| **Database ORM** | SQLAlchemy | 2.0.54 | Declarative 2.0 mapping across 22 normalized relational tables. |
| **Database** | PostgreSQL | 16 (Docker) | Relational persistence, row-level locking, append-only audit trail. |
| **AI / Multimodal** | `google-genai` SDK | 2.29.0 | Interface to `gemini-3.8-flash` (with `gemini-2.5-flash` fallback). |
| **PDF Processing** | `pypdf` | 6.19.0 | Local text extraction fallback and PDF structural security scanning. |
| **Storage Encryption** | `cryptography` | 50.0.2 | AES-256-GCM authenticated encryption at rest. |
| **Frontend Framework** | React | 19.2.8 | Interactive single-page application and review workspace. |
| **Language & Typings** | TypeScript | ~6.0.2 | End-to-end type safety matching backend DTO schemas. |
| **Frontend Tooling** | Vite | 8.3.2 | Build tooling and development server. |
| **Styling** | Tailwind CSS | 4.3.3 | Responsive utility-first layout. |
| **Testing** | Pytest / Vitest | 9.1.1 / 5.0.3 | Backend and frontend automated test runners. |

---

## 7. Key Engineering Decisions

### 1. Separation of Probabilistic AI Intake from Deterministic Verification
Large language models are probabilistic systems. While they are exceptional at visual document layout comprehension, multilingual text extraction, and reading complex tables, they are susceptible to hallucinations, stochastic variances, and token-level arithmetic errors. In construction commercial accounting, non-deterministic approval is unacceptable.

CIV divides responsibility:
- **Gemini is used exclusively for extraction (Stage 1):** Parsing PDFs into structured Pydantic schemas.
- **The Python engine executes all verification (Stage 2):** Pure mathematical functions using exact `Decimal` arithmetic, rate checks, cap tracking, and zero quantity tolerance.

### 2. Untrusted Field Quarantine Boundary
All fields extracted by Gemini enter the database with status `EXTRACTED` and method `LLM`. They are **never automatically trusted**. If verification is run while fields remain unconfirmed, the engine raises:
- `TRUST_001`: *"Invoice Line quantity value has not been human-confirmed"* (Outcome: `UNCERTAIN`, Severity: `WARNING`).
- `TRUST_002`: *"Delivered quantity on DN Line is not human-confirmed"* (Outcome: `UNCERTAIN`, Severity: `WARNING`).

An unconfirmed extraction **cannot produce a clean match**. A Quantity Surveyor must visually inspect the side-by-side document modal and explicitly confirm or edit the values.

### 3. Dual-Layer Delivery Note Deduplication
To prevent suppliers from billing the same delivery ticket twice across different cases or contracts, CIV evaluates both:
1. **Document SHA-256 Hash:** Checks whether the identical binary file has been uploaded elsewhere.
2. **Normalized Reference Key:** Normalizes the delivery ticket string and supplier Tax Registration Number (TRN).

If a match is found in any prior case, rule `DN_REUSE_001` emits a permanent `CRITICAL MISMATCH` citing the conflicting case IDs.

### 4. Zero Automated Payment Initiation
CIV verifies commercial accuracy and produces auditable findings and sign-off records. It deliberately does **not** execute automated bank transfers or integrate with payment rails, ensuring human commercial reviewers retain decision authority.

---

## 8. Implemented Verification Rules

The deterministic verification engine (`app/domain/engine.py`) implements **22 distinct domain rule codes**:

| Rule Code | Category | Severity | Domain Policy & Enforcement |
| :--- | :--- | :--- | :--- |
| `COMP_001` | Completeness | CRITICAL | Invoice document or invoice number is absent. |
| `COMP_002` | Completeness | CRITICAL | No delivery notes uploaded. Proof of delivery required for quantity verification. |
| `LPO_001` | LPO | INFO | LPO check not applicable (valid documented waiver code, e.g. framework agreement). |
| `LPO_002` | LPO | CRITICAL | LPO is marked as required, but no LPO document is attached. |
| `LPO_CAP_EXCEEDED` | LPO | CRITICAL | Cumulative invoiced quantity exceeds authorized contractual LPO cap. |
| `LPO_CAP_OK` | LPO | INFO | Cumulative invoiced quantity is within authorized LPO cap. |
| `RATE_MISMATCH` | Price | CRITICAL | Invoiced unit rate differs from contractual LPO unit rate. |
| `RATE_MATCH` | Price | INFO | Invoiced unit rate matches contractual LPO unit rate. |
| `CURR_001` | Currency | CRITICAL | Invoice currency is not AED. (Zero FX conversions permitted in UAE baseline). |
| `DN_REUSE_001` | DN Security | CRITICAL | Delivery note number or file SHA-256 matches a previously reconciled case. |
| `LINK_002` | Link Integrity | CRITICAL | Delivery note line linked to multiple invoice lines. |
| `QTY_CHARGE_001` | Quantity | INFO | Charge/service line excluded from physical delivery note quantity reconciliation. |
| `QTY_001` | Quantity | CRITICAL | Material invoice line has no linked delivery note lines. |
| `TRUST_001` | Trust Gate | WARNING | Invoice Line quantity value has not been human-confirmed (`UNCERTAIN`). |
| `TRUST_002` | Trust Gate | WARNING | Delivery Note Line quantity value has not been human-confirmed (`UNCERTAIN`). |
| `UNIT_001` | Unit Harmony | CRITICAL | Incompatible units between invoice and delivery note without a conversion rule. |
| `REJ_001` | Rejections | WARNING | Documented rejection evidence missing on ticket; deduction not made (`UNCERTAIN`). |
| `REJ_002` | Rejections | CRITICAL | Invalid rejection: rejected quantity exceeds delivered quantity. |
| `QTY_002` | Quantity | WARNING | Line comparison provisional: one or more delivery note values unconfirmed (`UNCERTAIN`). |
| `QTY_003` | Quantity | INFO | Exact quantity match between invoiced quantity and accepted delivered quantity. |
| `QTY_004` | Quantity | CRITICAL | Exact quantity mismatch: invoiced quantity differs from accepted delivered quantity. |
| `ARITH_001` | Arithmetic | CRITICAL | Line arithmetic discrepancy: `invoiced_qty * unit_price != line_amount`. |
| `ARITH_002` | Arithmetic | CRITICAL | Subtotal discrepancy: sum of line amounts differs from stated subtotal. |
| `ARITH_003` | Arithmetic | CRITICAL | Grand total discrepancy: `subtotal + tax_amount != grand_total`. |
| `VAT_UAE_000` | UAE VAT | INFO | Automated VAT verification gated (`NOT_CHECKED`) pending certified tax rules. |

---

## 9. Security Controls

- **AES-256-GCM Authenticated Encryption at Rest:** Files stored on disk are encrypted using `cryptography.hazmat.primitives.ciphers.aead.AESGCM` with a 12-byte random nonce and 16-byte authentication tag. Key material is derived via SHA-256 from `STORAGE_ENCRYPTION_KEY`.
- **PDF Active Content & Executable Detection:** Analyzes uploaded PDF byte streams for embedded JavaScript (`/JavaScript`, `/JS`), launch actions (`/Launch`), and executable file extensions (`.exe`, `.bat`, `.ps1`).
- **MIME & Magic-Byte Validation:** Enforces strict magic-byte checks (`%PDF-`, image headers), rejecting disguised payloads. Enforces a 20 MB size limit and 50-page maximum.
- **ClamAV Antivirus Streaming Client:** Implements an in-memory socket client communicating with the ClamAV daemon (`clamd`) via the `INSTREAM` protocol over TCP port 3310. Configured for fail-closed evaluation.
- **JWT Authentication & Project-Scoped RBAC:** Implements OAuth2 Bearer JWT authentication (HS256) with 30-minute access tokens and 8-hour refresh tokens. Active sessions are tracked in `user_session` for explicit revocation. Access is scoped to assigned projects (`project_user`).
- **Separation of Duties (SoD):** Users who create a case or upload documents are barred by backend logic from submitting the final commercial review decision.
- **Append-Only Audit Ledger:** Immutable audit trail table (`audit_event`) capturing actor IDs, timestamps, entity references, and previous/after states for all actions.

---

## 10. Testing Results

The codebase has been verified with automated test suites:

- **Backend Test Suite (Pytest 9.1.1):**
  - **124 passed, 0 failed** across 12 test modules (executed in 44.54s).
  - *Coverage Note:* The test suite achieves a **100% pass rate** (124/124 tests). Code line/branch coverage percentage was not instrumented via coverage tooling and is not claimed as 100% line coverage.
- **Frontend Test Suite (Vitest 5.0.3):**
  - **33 passed, 0 failed** across 3 test suites (`adapters.test.ts`, `createWorkflow.test.ts`, `reviewValidation.test.ts` in 218ms).
- **Frontend Production Build (TypeScript & Vite):**
  - Clean production build (`tsc -b && vite build`) producing `dist/assets/index-fTxI1GH4.js` (349.87 kB, gzip: 98.71 kB) with **0 TypeScript errors**.

---

## 11. Screenshots & UI Walkthrough

*(Screenshots captured from live prototype demonstration runs in local development environment)*

| Screen | Description |
| :--- | :--- |
| **Invoices Register** | Master register displaying verification cases, status badges (`READY_FOR_REVIEW`, `VERIFIED`), suppliers, and contract summaries. |
| **Verify Workspace** | Operational workspace with Documents, Data Entry, Link Evidence, and Verification Findings sub-tabs. |
| **Side-by-Side Field Review** | Interactive drawer displaying the PDF alongside extracted fields with confidence badges, edit options, and confirmation controls. |
| **Verification Findings Matrix** | Detailed breakdown of findings showing rule codes, severity badges, and exact discrepancies (e.g., +5.00 tonne steel overbilling). |
| **Commercial Review Modal** | Governance interface allowing authorized reviewers to record formal dispositions (`ACCEPT`, `DISPUTE`, `HOLD`) and notes. |

#### Case 1: Invoices Register & Operational Workspace
![CIV Verification Overview](artifacts/CIV_Overview.png)

#### Case 2: Quantity Discrepancy Flagged (+5.00 Tonne Overbilling)
![CIV Quantity Discrepancy](artifacts/CIV_Quantity_Discrepancy.png)

#### Case 3: Missing Delivery Evidence Guardrail
![CIV Missing Evidence](artifacts/CIV_Missing_Evidence.png)


---

## 12. Local Installation & Setup

### Prerequisites
- Python 3.10+
- Node.js v20+ or v22+ and npm
- Docker Desktop (for local PostgreSQL container)
- Google Gemini API key (optional, for live AI extraction; automated tests use mocked responses)

### Step 1: Clone Repository
```powershell
git clone <repository-url>
cd <repository-folder>
```

### Step 2: Start PostgreSQL Container
```powershell
docker run -d --name civ-pilot-postgres -p 5432:5432 `
  -e POSTGRES_USER=civ_user `
  -e POSTGRES_PASSWORD=civ_password `
  -e POSTGRES_DB=civ_pilot `
  postgres:16-alpine
```

### Step 3: Setup Backend Virtual Environment & Environment Variables
```powershell
cd D:\Invoice\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Configure local development environment variables
$env:APP_ENV="development"
$env:DATABASE_URL="postgresql://civ_user:civ_password@127.0.0.1:5432/civ_pilot"
$env:JWT_SECRET_KEY="civ-dev-test-jwt-secret-key-32-chars-minimum-local-only"
$env:STORAGE_ENCRYPTION_KEY="civ-dev-test-clean-storage-aes256-encryption-key-32b"

# Optional: configure Gemini API key for live AI extraction
$env:GEMINI_API_KEY="your-gemini-api-key"
$env:GEMINI_MODEL="gemini-3.8-flash"
```

### Step 4: Start FastAPI Backend
```powershell
python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```
Backend API will be accessible at `http://127.0.0.1:8000`. OpenAPI documentation is available at `http://127.0.0.1:8000/docs`.

### Step 5: Setup & Start Frontend
```powershell
cd D:\Invoice\frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```
Open `http://127.0.0.1:5173` in your browser.

### Local Demo Credentials
In development mode, pre-seeded local demonstration accounts are available in the login modal:
- **Project QS:** `ramesh.qs@pilot.civ.local` (Password: `PilotPass123!`) — Data entry and line linking.
- **Commercial Reviewer / PM:** `david.pm@pilot.civ.local` (Password: `PilotPass123!`) — Verification sign-off authority.
- **Commercial Director / Admin:** `khalfan.director@pilot.civ.local` (Password: `PilotPass123!`) — Administrative oversight.

*(Note: These credentials are strictly local development placeholders seeded in `seed.py` and are not used in production).*

### Step 6: Running Automated Tests
```powershell
# Run backend tests (124 tests)
cd D:\Invoice\backend
pytest tests/ -v

# Run frontend unit tests (33 tests)
cd D:\Invoice\frontend
npm test -- --run

# Run frontend production build check
npm run build
```

---

## 13. Limitations & Future Roadmap

To maintain engineering integrity, CIV explicitly documents its current architectural scope and limitations:

1. **Synthetic Data & Portfolio Status:** The system is an engineering prototype. All data, vendor names, contracts, and documents are synthetic. It is not currently deployed in commercial production.
2. **No Automated Payment Execution:** CIV is an operational verification and commercial governance platform. It does **not** disburse funds, execute bank transfers, or connect to banking gateways. All review decisions generate auditable sign-off records for downstream processing.
3. **Automated UAE VAT Rules Gated:** Rule `VAT_UAE_000` remains intentionally gated (`NOT_CHECKED`) pending certified integration with UAE Federal Tax Authority (FTA) calculation schedules.
4. **Single-Document Extraction Workflow:** Multimodal extraction operates on individual uploaded documents. In real-world site administration, delivery tickets are sometimes scanned in large 50-page mixed PDF binders; an upstream document-splitting service is planned for future milestones.
5. **No Direct ERP Connectors:** Invoicing and review records are stored in PostgreSQL with REST API export endpoints. Bi-directional sync with enterprise ERPs (SAP S/4HANA, Oracle Primavera) is a planned future roadmap item.

---

## 14. Documentation & References

- **Project:** Construction Invoice Verification (CIV) Engineering Portfolio Prototype
- **Role Target:** Junior Full-Stack / Python Backend / Applied AI Engineer
- **Executive Commercial Summary:** [`docs/CIV_Executive_Summary.md`](docs/CIV_Executive_Summary.md)
