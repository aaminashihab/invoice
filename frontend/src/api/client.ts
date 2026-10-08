/**
 * Typed HTTP client for Construction Invoice Verification API (127.0.0.1:8000).
 * Strictly communicates with local loopback endpoints.
 */

export const API_BASE_URL = '/api/v1'

export interface ApiProject {
  id?: string
  code: string
  name: string
  site_location?: string
}

export interface ApiSupplier {
  id?: string
  name: string
  trn: string
}

export interface ApiDocument {
  id: string
  case_id?: string
  doc_type: 'INVOICE' | 'DELIVERY_NOTE' | 'LPO'
  original_filename: string
  mime_type?: string
  size_bytes?: number
  sha256?: string
  page_count?: number
  quarantine_status?: string
  is_quarantined?: boolean
  reference_no_normalized?: string
}

export interface ApiFinding {
  id: string
  category: string
  rule_code: string
  outcome: string
  severity: string
  message: string
  expected?: string | null
  actual?: string | null
  difference?: string | null
  difference_pct?: string | null
  subject_type?: string | null
  subject_id?: string | null
  unit?: string | null
  details?: Record<string, unknown>
  rule_status?: string
  numeric_policy?: string | null
}

export interface ApiRun {
  id: string
  run_no: number
  summary: string
  summary_labels: string[]
  findings: ApiFinding[]
}

export interface ApiAuditEvent {
  id: string
  action: string
  actor_id?: string | null
  at: string
  entity_type: string
  after_state?: Record<string, unknown>
}

export interface ApiDisposition {
  id: string
  finding_id: string
  disposition: string
  comment: string
}

export interface ApiReview {
  id: string
  run_id: string
  reviewer_id: string
  reviewer_name?: string | null
  outcome: string
  comment: string
  declaration_accepted: boolean
  qualifiers: string[]
  created_at: string
  dispositions: ApiDisposition[]
}

export interface ApiLpoSummary {
  id: string
  lpo_number: string
  project_id: string
  project_code?: string | null
  supplier_id: string
  supplier_name?: string | null
  lpo_date: string
  currency: string
  total_amount_cap?: string | null
  lines_count: number
  created_at: string
}

export interface ApiLpoLine {
  id: string
  line_no: number
  material_id?: string | null
  description: string
  ordered_qty: string
  unit: string
  agreed_unit_price: string
  line_amount_cap?: string | null
  cumulative_consumed_qty?: string
  remaining_qty?: string
}

export interface ApiLpoDetail {
  id: string
  lpo_number: string
  project_id: string
  project_code?: string | null
  supplier_id: string
  supplier_name?: string | null
  lpo_date: string
  currency: string
  total_amount_cap?: string | null
  lines: ApiLpoLine[]
  created_at: string
}

export interface ApiCaseSummary {
  id: string
  case_ref: string
  project: ApiProject
  supplier: ApiSupplier
  lpo_id?: string | null
  lpo?: { id: string; lpo_number: string; total_amount_cap?: string | null } | null
  invoice_number_hint?: string | null
  currency: string
  lpo_required: boolean
  lpo_reason_code?: string | null
  lpo_reason_text?: string | null
  status: string
  created_at: string
}

export interface ApiCaseDetail extends ApiCaseSummary {
  lpo_reason_code?: string | null
  lpo_reason_text?: string | null
  documents: ApiDocument[]
  runs: ApiRun[]
  audit_events: ApiAuditEvent[]
  reviews: ApiReview[]
}

export interface UploadDocumentResponse {
  synthetic_data_only: boolean
  reuse_warning: boolean
  reuse_case_id?: string | null
  document: ApiDocument
}

export interface ReviewSubmitPayload {
  outcome: string
  comment: string
  declaration_accepted: boolean
  manual_vat_checked: boolean
  disposition_comment?: string
}

export interface ReviewSubmitResponse {
  banner: string
  synthetic_data_only: boolean
  review: ApiReview
  case_status: string
}

export interface UserProjectSummary {
  id: string
  code: string
  name: string
}

export interface UserProfile {
  id: string
  name: string
  email: string
  role: string
  can_review: boolean
  active: boolean
  assigned_projects: UserProjectSummary[]
}

export interface AuthTokens {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in_seconds: number
  user: UserProfile
}

export class ApiError extends Error {
  code: string
  status: number
  details?: unknown

  constructor(message: string, code: string, status: number, details?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.details = details
  }
}

let currentAuthToken: string | null = typeof localStorage !== 'undefined' ? localStorage.getItem('civ_access_token') : null

export function setAuthToken(token: string | null): void {
  currentAuthToken = token
  if (typeof localStorage !== 'undefined') {
    if (token) {
      localStorage.setItem('civ_access_token', token)
    } else {
      localStorage.removeItem('civ_access_token')
    }
  }
}

export function getAuthToken(): string | null {
  if (!currentAuthToken && typeof localStorage !== 'undefined') {
    currentAuthToken = localStorage.getItem('civ_access_token')
  }
  return currentAuthToken
}

export async function loginUser(email: string, password: string): Promise<AuthTokens> {
  const res = await fetch(`${API_BASE_URL}/auth/login`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify({ email, password }),
  })
  const data = await handleResponse<AuthTokens>(res)
  setAuthToken(data.access_token)
  if (typeof localStorage !== 'undefined' && data.refresh_token) {
    localStorage.setItem('civ_refresh_token', data.refresh_token)
  }
  return data
}

export async function fetchCurrentUser(): Promise<UserProfile> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  const token = getAuthToken()
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }
  const res = await fetch(`${API_BASE_URL}/auth/me`, { headers })
  return handleResponse<UserProfile>(res)
}

export async function logoutUser(): Promise<void> {
  const refreshToken = typeof localStorage !== 'undefined' ? localStorage.getItem('civ_refresh_token') : null
  if (refreshToken) {
    try {
      await fetch(`${API_BASE_URL}/auth/logout`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      })
    } catch {
      // Ignore network errors during logout
    }
  }
  setAuthToken(null)
  if (typeof localStorage !== 'undefined') {
    localStorage.removeItem('civ_refresh_token')
  }
}

export async function fetchLpos(projectId?: string, supplierId?: string): Promise<ApiLpoSummary[]> {
  const params = new URLSearchParams()
  if (projectId) params.append('project_id', projectId)
  if (supplierId) params.append('supplier_id', supplierId)
  const qs = params.toString() ? `?${params.toString()}` : ''
  const res = await fetch(`${API_BASE_URL}/lpos${qs}`, {
    headers: getAuthHeaders(),
  })
  const data = await handleResponse<{ lpos: ApiLpoSummary[] }>(res)
  return data.lpos || []
}

export async function fetchLpoDetail(lpoId: string): Promise<ApiLpoDetail> {
  const res = await fetch(`${API_BASE_URL}/lpos/${encodeURIComponent(lpoId)}`, {
    headers: getAuthHeaders(),
  })
  const data = await handleResponse<{ lpo: ApiLpoDetail }>(res)
  return data.lpo
}

export async function linkLpoToCase(caseId: string, lpoId: string): Promise<{ case_id: string; lpo_id: string; lpo_number: string }> {
  const headers = getAuthHeaders()
  headers['Content-Type'] = 'application/json'
  const res = await fetch(`${API_BASE_URL}/cases/${encodeURIComponent(caseId)}/link-lpo`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ lpo_id: lpoId }),
  })
  return handleResponse<{ case_id: string; lpo_id: string; lpo_number: string }>(res)
}

function getAuthHeaders(simulatedUser?: string): Record<string, string> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  const token = getAuthToken()
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  } else if (simulatedUser) {
    headers['X-Simulated-User'] = simulatedUser
  }
  return headers
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let errorDetail: { code?: string; message?: string; details?: unknown } = {}
    try {
      const data = await res.json()
      if (data && typeof data === 'object') {
        if ('detail' in data && typeof data.detail === 'object') {
          errorDetail = data.detail
        } else if ('error' in data && typeof data.error === 'object') {
          errorDetail = data.error
        } else if ('message' in data) {
          errorDetail = { message: String(data.message) }
        }
      }
    } catch {
      // response wasn't JSON
    }

    const code = errorDetail.code || `HTTP_${res.status}`
    const message = errorDetail.message || `Request failed with status ${res.status} (${res.statusText})`
    throw new ApiError(message, code, res.status, errorDetail.details)
  }
  return res.json()
}

export async function fetchCases(simulatedUser?: string): Promise<ApiCaseSummary[]> {
  const res = await fetch(`${API_BASE_URL}/cases`, {
    headers: getAuthHeaders(simulatedUser),
  })
  const data = await handleResponse<{ cases: ApiCaseSummary[] }>(res)
  return data.cases || []
}

export async function fetchCaseDetail(caseId: string, simulatedUser?: string): Promise<ApiCaseDetail> {
  const res = await fetch(`${API_BASE_URL}/cases/${encodeURIComponent(caseId)}`, {
    headers: getAuthHeaders(simulatedUser),
  })
  const data = await handleResponse<{ case: ApiCaseDetail }>(res)
  return data.case
}

export async function uploadDocument(
  caseId: string,
  file: File,
  docType: 'INVOICE' | 'DELIVERY_NOTE' | 'LPO',
  simulatedUser = 'sim-reviewer'
): Promise<UploadDocumentResponse> {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('doc_type', docType)

  const headers = getAuthHeaders(simulatedUser)
  delete headers['Accept'] // Let browser handle multipart form boundary

  const res = await fetch(`${API_BASE_URL}/cases/${encodeURIComponent(caseId)}/documents`, {
    method: 'POST',
    headers,
    body: formData,
  })

  return handleResponse<UploadDocumentResponse>(res)
}

export async function submitReview(
  caseId: string,
  payload: ReviewSubmitPayload,
  simulatedUser = 'sim-reviewer'
): Promise<ReviewSubmitResponse> {
  const headers = getAuthHeaders(simulatedUser)
  headers['Content-Type'] = 'application/json'

  const res = await fetch(`${API_BASE_URL}/cases/${encodeURIComponent(caseId)}/reviews`, {
    method: 'POST',
    headers,
    body: JSON.stringify(payload),
  })

  return handleResponse<ReviewSubmitResponse>(res)
}

export function getDocumentContentUrl(documentId: string): string {
  const token = getAuthToken()
  if (token) {
    return `${API_BASE_URL}/documents/${encodeURIComponent(documentId)}/content?token=${encodeURIComponent(token)}`
  }
  return `${API_BASE_URL}/documents/${encodeURIComponent(documentId)}/content`
}

