import { useState, useEffect } from 'react'
import {
  LayoutDashboard,
  FileCheck2,
  GitCompare,
  ClipboardList,
  History,
  Settings as SettingsIcon,
  Plus,
  FileText,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  HelpCircle,
  Ban,
  User,
  ChevronRight,
  ShieldCheck,
  Building2,
  X,
  Info,
  Lock,
  Upload,
  RefreshCw,
  ExternalLink,
  LogIn,
  LogOut,
} from 'lucide-react'
import {
  type ReviewOutcome,
  getPermittedReviewOutcomes,
  validateReviewSubmission,
  formatOutcomeOptionLabel,
  isReviewDecisionSubmittable,
  type CaseValidationDetails,
} from './utils/reviewValidation'
import {
  INITIAL_CREATE_WORKFLOW_STATE,
  openCreateWorkflow,
  closeCreateWorkflow,
} from './utils/createWorkflow'
import {
  API_BASE_URL,
  fetchCases,
  fetchCaseDetail,
  uploadDocument,
  submitReview,
  getDocumentContentUrl,
  fetchCurrentUser,
  loginUser,
  logoutUser,
  getAuthToken,
  ApiError,
  type ApiCaseDetail,
  type UserProfile,
} from './api/client'
import { mapCaseToInvoiceRecord, type ExtendedInvoiceRecord } from './api/adapters'

type NavTab = 'Dashboard' | 'Invoices' | 'Verify' | 'Review' | 'History' | 'Settings'

interface RulesetSummary {
  version: string
  quantity_policy: { status: string; rule: string }
  financial_rounding_policy: { status: string; rule: string }
  vat_policy: { status: string; reason: string; manual_check_allowed: boolean }
  payment_approval_policy: { status: string; rule: string }
}

const PILOT_ACCOUNTS = [
  {
    role: 'Commercial PM',
    name: 'David PM',
    email: 'david.pm@pilot.civ.local',
    desc: 'Project Manager (Reviewer)',
  },
  {
    role: 'Project QS',
    name: 'Ramesh QS',
    email: 'ramesh.qs@pilot.civ.local',
    desc: 'Quantity Surveyor (Reviewer)',
  },
  {
    role: 'Site Engineer',
    name: 'Ahmed Eng',
    email: 'ahmed.eng@pilot.civ.local',
    desc: 'Site Engineer (Verification)',
  },
  {
    role: 'Storekeeper',
    name: 'Tariq Store',
    email: 'tariq.store@pilot.civ.local',
    desc: 'Storekeeper (Receipts)',
  },
]

export function App() {
  const [tab, setTab] = useState<NavTab>('Dashboard')
  const [ruleset, setRuleset] = useState<RulesetSummary | null>(null)
  const [invoices, setInvoices] = useState<ExtendedInvoiceRecord[]>([])
  const [selectedCaseId, setSelectedCaseId] = useState<string>('')
  const [currentUser, setCurrentUser] = useState<UserProfile | null>(null)
  const [isLoading, setIsLoading] = useState<boolean>(true)
  const [apiError, setApiError] = useState<string | null>(null)
  
  // Document upload state
  const [uploadDocType, setUploadDocType] = useState<'DELIVERY_NOTE' | 'INVOICE' | 'LPO'>('DELIVERY_NOTE')
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [isUploading, setIsUploading] = useState<boolean>(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [uploadWarning, setUploadWarning] = useState<string | null>(null)

  // Review form state
  const [selectedOutcome, setSelectedOutcome] = useState<ReviewOutcome>('ON_HOLD_QUERIED')
  const [reviewerNote, setReviewerNote] = useState('')
  const [manualVatChecked, setManualVatChecked] = useState(false)
  const [declarationAccepted, setDeclarationAccepted] = useState(false)
  const [reviewValidationError, setReviewValidationError] = useState<string | null>(null)
  const [reviewSuccessMessage, setReviewSuccessMessage] = useState<string | null>(null)
  const [isSubmittingReview, setIsSubmittingReview] = useState<boolean>(false)

  // Create workflow placeholder state
  const [createWorkflow, setCreateWorkflow] = useState(INITIAL_CREATE_WORKFLOW_STATE)

  // Auth & Login modal state
  const [isLoginModalOpen, setIsLoginModalOpen] = useState(false)
  const [loginEmail, setLoginEmail] = useState('')
  const [loginPassword, setLoginPassword] = useState('')
  const [loginError, setLoginError] = useState<string | null>(null)
  const [isLoggingIn, setIsLoggingIn] = useState(false)

  const selectedCase = invoices.find((c) => c.id === selectedCaseId) || invoices[0] || null

  const loadAllCases = async () => {
    try {
      setIsLoading(true)
      setApiError(null)
      const summaries = await fetchCases()
      if (summaries.length === 0) {
        setInvoices([])
        return
      }

      const detailedCases = await Promise.all(
        summaries.map(async (s) => {
          try {
            return await fetchCaseDetail(s.id)
          } catch {
            return null
          }
        })
      )

      const mapped = detailedCases
        .filter((d): d is ApiCaseDetail => d !== null)
        .map((d) => mapCaseToInvoiceRecord(d))

      if (mapped.length > 0) {
        setInvoices(mapped)
        if (!mapped.some((m) => m.id === selectedCaseId)) {
          const defaultCase = mapped.find((m) => m.id === 'case-synth-02') || mapped[0]
          setSelectedCaseId(defaultCase.id)
        }
      } else {
        setInvoices([])
      }
    } catch (err) {
      console.error('Failed to load cases from API:', err)
      if (err instanceof ApiError && err.status === 401) {
        setApiError('Please sign in to continue.')
        setCurrentUser(null)
      } else {
        setApiError('Unable to connect to verification backend.')
      }
      setInvoices([])
    } finally {
      setIsLoading(false)
    }
  }

  const handleLogin = async (e?: React.FormEvent) => {
    if (e) e.preventDefault()
    setIsLoggingIn(true)
    setLoginError(null)
    try {
      await loginUser(loginEmail, loginPassword)
      const user = await fetchCurrentUser()
      setCurrentUser(user)
      setIsLoginModalOpen(false)
      setLoginEmail('')
      setLoginPassword('')
      await loadAllCases()
    } catch (err: any) {
      console.error('Login failed:', err)
      setLoginError(err?.message || 'Authentication failed. Please verify credentials.')
    } finally {
      setIsLoggingIn(false)
    }
  }

  const handleLogout = async () => {
    await logoutUser()
    setCurrentUser(null)
    setInvoices([])
    setApiError('Please sign in to continue.')
  }

  const refreshCase = async (caseId: string) => {
    try {
      const detail = await fetchCaseDetail(caseId)
      const mapped = mapCaseToInvoiceRecord(detail)
      setInvoices((prev) =>
        prev.map((inv) => (inv.id === caseId ? mapped : inv))
      )
    } catch (err) {
      console.error(`Failed to refresh case ${caseId}:`, err)
    }
  }

  useEffect(() => {
    fetch(`${API_BASE_URL}/ruleset`)
      .then((res) => res.json())
      .then((data) => setRuleset(data))
      .catch(() => setRuleset(null))

    if (getAuthToken()) {
      fetchCurrentUser()
        .then((user) => {
          setCurrentUser(user)
          loadAllCases()
        })
        .catch(() => {
          setCurrentUser(null)
          setApiError('Please sign in to continue.')
          setIsLoading(false)
        })
    } else {
      setCurrentUser(null)
      setApiError('Please sign in to continue.')
      setIsLoading(false)
    }
  }, [])

  // Derive validation details for the selected case
  const validationDetails: CaseValidationDetails = {
    caseId: selectedCase ? selectedCase.id : '',
    hasQuantityMismatch: selectedCase ? selectedCase.hasQuantityMismatch : false,
    hasMissingEvidence: selectedCase ? selectedCase.hasMissingEvidence : false,
    hasUncertainEvidence: selectedCase ? selectedCase.hasUncertainEvidence : false,
    hasUnitIncompatible: selectedCase ? selectedCase.hasUnitIncompatible : false,
    hasDnReuse: selectedCase ? selectedCase.hasDnReuse : false,
    manualVatCheckDocumented: manualVatChecked,
    vatAutomatedStatus: 'NOT_CHECKED',
  }

  const permittedOutcomes = getPermittedReviewOutcomes(validationDetails)

  const isReviewSubmittable = isReviewDecisionSubmittable({
    outcome: selectedOutcome,
    allowedOutcomes: permittedOutcomes,
    reviewerNote,
    declarationAccepted,
  })

  // Auto-align selected outcome if current is disallowed
  useEffect(() => {
    const currentOption = permittedOutcomes.find((o) => o.value === selectedOutcome)
    if (!currentOption || !currentOption.allowed) {
      const firstAllowed = permittedOutcomes.find((o) => o.allowed)
      if (firstAllowed) {
        setSelectedOutcome(firstAllowed.value)
      }
    }
  }, [selectedCaseId, manualVatChecked, permittedOutcomes, selectedOutcome])

  const countTotal = invoices.length
  const countPending = invoices.filter((i) => i.status === 'Pending').length
  const countMismatch = invoices.filter((i) => i.status === 'Mismatch').length
  const countMissing = invoices.filter((i) => i.status === 'Missing').length

  const handleUploadDocument = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!uploadFile) {
      setUploadError('Please select a file to attach.')
      return
    }
    if (!selectedCase) return

    setIsUploading(true)
    setUploadError(null)
    setUploadWarning(null)

    try {
      const res = await uploadDocument(selectedCase.id, uploadFile, uploadDocType, 'sim-reviewer')
      if (res.reuse_warning) {
        setUploadWarning(
          `Document uploaded, but duplicate file content was detected across cases (${res.reuse_case_id || 'another case'}). Delivery note reuse is permanently flagged per Rule C1.`
        )
      }
      setUploadFile(null)
      const fileInput = document.getElementById('doc-file-input') as HTMLInputElement | null
      if (fileInput) fileInput.value = ''

      await refreshCase(selectedCase.id)
    } catch (err) {
      if (err instanceof ApiError) {
        setUploadError(`Upload Rejected [${err.code}]: ${err.message}`)
      } else {
        setUploadError(`Upload failed: ${String(err)}`)
      }
    } finally {
      setIsUploading(false)
    }
  }

  const handleSaveReview = async () => {
    setReviewValidationError(null)

    const result = validateReviewSubmission({
      outcome: selectedOutcome,
      allowedOutcomes: permittedOutcomes,
      reviewerNote,
      declarationAccepted,
    })

    if (!result.isValid) {
      setReviewValidationError(result.error || 'Review validation failed.')
      return
    }

    if (!selectedCase) return

    try {
      setIsSubmittingReview(true)
      await submitReview(
        selectedCase.id,
        {
          outcome: selectedOutcome,
          comment: reviewerNote.trim(),
          declaration_accepted: declarationAccepted,
          manual_vat_checked: manualVatChecked,
        },
        'sim-reviewer'
      )

      await refreshCase(selectedCase.id)

      const outcomeLabel =
        permittedOutcomes.find((o) => o.value === selectedOutcome)?.label || selectedOutcome
      setReviewSuccessMessage(
        `Review persisted to case audit trail (Outcome: "${outcomeLabel}"). [Mandatory human sign-off recorded • No disbursement initiated]`
      )
      setTimeout(() => setReviewSuccessMessage(null), 6000)
      setTab('History')
    } catch (err) {
      if (err instanceof ApiError) {
        setReviewValidationError(`Review Submission Failed [${err.code}]: ${err.message}`)
      } else {
        setReviewValidationError(`Failed to submit review: ${String(err)}`)
      }
    } finally {
      setIsSubmittingReview(false)
    }
  }

  const renderStatus = (status: string) => {
    switch (status) {
      case 'Matched':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-emerald-50 text-emerald-700 border border-emerald-200">
            <CheckCircle2 className="w-3 h-3 text-emerald-600" />
            Matched
          </span>
        )
      case 'Mismatch':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-rose-50 text-rose-700 border border-rose-200">
            <XCircle className="w-3 h-3 text-rose-600" />
            Mismatch
          </span>
        )
      case 'Missing':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-amber-50 text-amber-700 border border-amber-200">
            <AlertTriangle className="w-3 h-3 text-amber-600" />
            Missing
          </span>
        )
      case 'Uncertain':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-slate-100 text-slate-700 border border-slate-300">
            <HelpCircle className="w-3 h-3 text-slate-500" />
            Uncertain
          </span>
        )
      default:
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-blue-50 text-blue-700 border border-blue-200">
            Pending
          </span>
        )
    }
  }

  const renderReviewStatus = (outcome?: string) => {
    if (!outcome) return null
    switch (outcome) {
      case 'Verified (Clean Match)':
        return (
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-emerald-50 text-emerald-700 border border-emerald-200">
            <CheckCircle2 className="w-2.5 h-2.5 text-emerald-600" />
            {outcome}
          </span>
        )
      case 'Verified (With Exceptions)':
        return (
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-teal-50 text-teal-700 border border-teal-200">
            <CheckCircle2 className="w-2.5 h-2.5 text-teal-600" />
            {outcome}
          </span>
        )
      case 'On Hold (Queried)':
        return (
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-50 text-amber-700 border border-amber-200">
            <AlertTriangle className="w-2.5 h-2.5 text-amber-600" />
            {outcome}
          </span>
        )
      case 'Rejected':
        return (
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-rose-50 text-rose-700 border border-rose-200">
            <XCircle className="w-2.5 h-2.5 text-rose-600" />
            {outcome}
          </span>
        )
      default:
        return (
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-slate-100 text-slate-700 border border-slate-200">
            {outcome}
          </span>
        )
    }
  }

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 flex flex-col font-sans antialiased">
      {/* Top Bar: Safety & Environment */}
      <div className="bg-slate-900 text-slate-300 text-xs px-5 py-1.5 flex items-center justify-between border-b border-slate-800">
        <div className="flex items-center gap-3">
          <span className="font-semibold text-teal-400 tracking-wider text-[11px] uppercase">
            Synthetic
          </span>
          <span className="text-slate-500">•</span>
          <span className="text-slate-400">Local Prototype</span>
          <span className="text-slate-500">•</span>
          <span className="text-slate-400">M1 Verification Rules Active</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-rose-400 font-medium flex items-center gap-1">
            <Ban className="w-3 h-3" />
            No Auto-Pay
          </span>
          <span className="text-slate-500">•</span>
          <div className="flex items-center gap-1.5 text-slate-300">
            <User className="w-3 h-3 text-teal-400" />
            <span>{currentUser ? currentUser.name : 'Unauthenticated'}</span>
            <span className="bg-slate-800 text-teal-300 text-[10px] px-1 rounded uppercase font-mono">
              {currentUser ? currentUser.role : 'Guest'}
            </span>
            {currentUser && currentUser.assigned_projects && currentUser.assigned_projects.length > 0 && (
              <span
                className="text-slate-400 text-[10px] hidden sm:inline"
                title={currentUser.assigned_projects.map((p) => `${p.code} (${p.name})`).join(', ')}
              >
                ({currentUser.assigned_projects.length} {currentUser.assigned_projects.length === 1 ? 'project' : 'projects'})
              </span>
            )}
            {currentUser ? (
              <button
                onClick={handleLogout}
                className="ml-2 flex items-center gap-1 text-[11px] text-rose-300 hover:text-rose-200 transition-colors bg-slate-800 px-2 py-0.5 rounded cursor-pointer"
                title="Sign Out"
              >
                <LogOut className="w-3 h-3" />
                <span>Sign Out</span>
              </button>
            ) : (
              <button
                onClick={() => setIsLoginModalOpen(true)}
                className="ml-2 flex items-center gap-1 text-[11px] text-teal-300 hover:text-teal-200 transition-colors bg-slate-800 px-2 py-0.5 rounded cursor-pointer"
                title="Sign In"
              >
                <LogIn className="w-3 h-3" />
                <span>Sign In</span>
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="flex flex-1">
        {/* Compact Sidebar */}
        <aside className="w-56 bg-white border-r border-slate-200 flex flex-col shrink-0">
          <div className="p-4 border-b border-slate-100 flex items-center gap-2.5">
            <div className="bg-slate-900 text-teal-400 p-1.5 rounded-md">
              <Building2 className="w-4 h-4" />
            </div>
            <div>
              <div className="text-xs font-bold text-slate-900 uppercase tracking-tight">
                CIV Engine
              </div>
              <div className="text-[10px] text-slate-400">UAE • AED</div>
            </div>
          </div>

          <nav className="p-2 space-y-0.5 flex-1 text-xs font-medium text-slate-600">
            <button
              onClick={() => setTab('Dashboard')}
              className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-md transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 ${
                tab === 'Dashboard'
                  ? 'bg-slate-900 text-white font-semibold'
                  : 'hover:bg-slate-100 hover:text-slate-900'
              }`}
            >
              <LayoutDashboard className="w-3.5 h-3.5 text-teal-400" />
              <span>Dashboard</span>
            </button>

            <button
              onClick={() => setTab('Invoices')}
              className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-md transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 ${
                tab === 'Invoices'
                  ? 'bg-slate-900 text-white font-semibold'
                  : 'hover:bg-slate-100 hover:text-slate-900'
              }`}
            >
              <FileCheck2 className="w-3.5 h-3.5 text-teal-400" />
              <span>Invoices</span>
            </button>

            <button
              onClick={() => setTab('Verify')}
              className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-md transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 ${
                tab === 'Verify'
                  ? 'bg-slate-900 text-white font-semibold'
                  : 'hover:bg-slate-100 hover:text-slate-900'
              }`}
            >
              <GitCompare className="w-3.5 h-3.5 text-teal-400" />
              <span>Verify</span>
            </button>

            <button
              onClick={() => setTab('Review')}
              className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-md transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 ${
                tab === 'Review'
                  ? 'bg-slate-900 text-white font-semibold'
                  : 'hover:bg-slate-100 hover:text-slate-900'
              }`}
            >
              <ClipboardList className="w-3.5 h-3.5 text-teal-400" />
              <span>Review</span>
            </button>

            <button
              onClick={() => setTab('History')}
              className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-md transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 ${
                tab === 'History'
                  ? 'bg-slate-900 text-white font-semibold'
                  : 'hover:bg-slate-100 hover:text-slate-900'
              }`}
            >
              <History className="w-3.5 h-3.5 text-teal-400" />
              <span>History</span>
            </button>

            <button
              onClick={() => setTab('Settings')}
              className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-md transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 ${
                tab === 'Settings'
                  ? 'bg-slate-900 text-white font-semibold'
                  : 'hover:bg-slate-100 hover:text-slate-900'
              }`}
            >
              <SettingsIcon className="w-3.5 h-3.5 text-teal-400" />
              <span>Settings</span>
            </button>
          </nav>

          <div className="p-3 border-t border-slate-100 text-[10px] text-slate-400 flex items-center justify-between">
            <span>M1 Engine</span>
            <span className="text-emerald-600 font-mono font-medium">Active</span>
          </div>
        </aside>

        {/* Main Content Area */}
        <main className="flex-1 flex flex-col overflow-y-auto">
          {/* Header */}
          <header className="bg-white border-b border-slate-200 px-6 py-3.5 flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm text-slate-500 font-medium">
              <span>CIV</span>
              <ChevronRight className="w-3.5 h-3.5 text-slate-400" />
              <span className="text-slate-900 font-semibold">{tab}</span>
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={() => setCreateWorkflow(openCreateWorkflow(createWorkflow))}
                className="bg-slate-100 hover:bg-slate-200 text-slate-500 text-xs font-semibold px-3 py-1.5 rounded-md flex items-center gap-1.5 transition-colors border border-slate-200 shadow-2xs"
                title="Case creation is disabled in prototype"
              >
                <Plus className="w-3.5 h-3.5 text-slate-400" />
                <span>+ Create Case (Disabled)</span>
              </button>
            </div>
          </header>

          {/* Feedback Banners */}
          {reviewSuccessMessage && (
            <div className="mx-6 mt-4 p-3 bg-emerald-50 border border-emerald-200 rounded-md text-emerald-900 text-xs flex items-center justify-between shadow-2xs">
              <div className="flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
                <span>{reviewSuccessMessage}</span>
              </div>
              <button
                onClick={() => setReviewSuccessMessage(null)}
                className="text-emerald-600 hover:text-emerald-900"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          )}

          {apiError && (
            <div className="mx-6 mt-4 p-3 bg-amber-50 border border-amber-200 rounded-md text-amber-900 text-xs flex items-center justify-between shadow-2xs">
              <div className="flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0" />
                <span>{apiError}</span>
              </div>
              <div className="flex items-center gap-3">
                {!currentUser && (
                  <button
                    onClick={() => setIsLoginModalOpen(true)}
                    className="text-teal-700 hover:text-teal-900 font-semibold inline-flex items-center gap-1 cursor-pointer"
                  >
                    <LogIn className="w-3.5 h-3.5" />
                    <span>Sign In</span>
                  </button>
                )}
                <button
                  onClick={() => loadAllCases()}
                  className="text-amber-700 hover:text-amber-900 font-semibold inline-flex items-center gap-1 cursor-pointer"
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                  <span>Retry</span>
                </button>
              </div>
            </div>
          )}

          <div className="p-6 max-w-6xl w-full mx-auto space-y-6">
            {/* TAB: DASHBOARD */}
            {tab === 'Dashboard' && (
              <div className="space-y-6">
                {/* 4 Compact Metric Cards */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <div className="bg-white border border-slate-200 rounded-lg p-4 shadow-2xs">
                    <div className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
                      Total
                    </div>
                    <div className="text-2xl font-bold text-slate-900 mt-1 font-mono">
                      {countTotal}
                    </div>
                  </div>

                  <div className="bg-white border border-slate-200 rounded-lg p-4 shadow-2xs">
                    <div className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
                      Pending
                    </div>
                    <div className="text-2xl font-bold text-blue-600 mt-1 font-mono">
                      {countPending}
                    </div>
                  </div>

                  <div className="bg-white border border-slate-200 rounded-lg p-4 shadow-2xs">
                    <div className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
                      Mismatches
                    </div>
                    <div className="text-2xl font-bold text-rose-600 mt-1 font-mono">
                      {countMismatch}
                    </div>
                  </div>

                  <div className="bg-white border border-slate-200 rounded-lg p-4 shadow-2xs">
                    <div className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
                      Missing
                    </div>
                    <div className="text-2xl font-bold text-amber-600 mt-1 font-mono">
                      {countMissing}
                    </div>
                  </div>
                </div>

                {/* Table */}
                <div className="bg-white border border-slate-200 rounded-lg shadow-2xs overflow-hidden">
                  <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between bg-slate-50/50">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-bold text-slate-900 uppercase tracking-wider">
                        Register
                      </span>
                      <span className="text-[10px] bg-emerald-100 text-emerald-800 px-1.5 py-0.5 rounded font-mono font-medium">
                        Persisted SQLite Cases
                      </span>
                      <button
                        onClick={() => loadAllCases()}
                        disabled={isLoading}
                        className="text-slate-500 hover:text-slate-900 p-1 rounded"
                        title="Reload cases from backend API"
                      >
                        <RefreshCw className={`w-3 h-3 ${isLoading ? 'animate-spin text-teal-600' : ''}`} />
                      </button>
                    </div>
                    <button
                      onClick={() => setCreateWorkflow(openCreateWorkflow(createWorkflow))}
                      className="text-xs text-slate-400 font-semibold hover:text-slate-600 flex items-center gap-1"
                      title="Case creation is disabled in prototype"
                    >
                      <Plus className="w-3 h-3" />
                      <span>+ Create Case (Disabled)</span>
                    </button>
                  </div>

                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-xs">
                      <thead className="bg-slate-50 border-b border-slate-200 text-slate-600 font-semibold uppercase text-[10px] tracking-wider">
                        <tr>
                          <th className="py-2.5 px-4">Supplier</th>
                          <th className="py-2.5 px-4">Invoice</th>
                          <th className="py-2.5 px-4">Project</th>
                          <th className="py-2.5 px-4 text-right">Amount (AED)</th>
                          <th className="py-2.5 px-4">Status</th>
                          <th className="py-2.5 px-4">Rule Notes</th>
                          <th className="py-2.5 px-4 text-right">Action</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100 text-slate-700">
                        {invoices.length === 0 ? (
                          <tr>
                            <td colSpan={7} className="py-8 text-center text-slate-500 text-xs">
                              {isLoading
                                ? 'Loading verification cases from API...'
                                : apiError
                                ? apiError
                                : 'No verification cases available.'}
                            </td>
                          </tr>
                        ) : (
                          invoices.map((inv) => (
                            <tr key={inv.id} className="hover:bg-slate-50/80 transition-colors">
                              <td className="py-3 px-4 font-medium text-slate-900">
                                <div>{inv.supplier}</div>
                                <div className="text-[10px] font-mono text-slate-400">
                                  TRN: {inv.supplierTrn}
                                </div>
                              </td>
                              <td className="py-3 px-4 font-mono text-slate-600">{inv.invoiceNo}</td>
                              <td className="py-3 px-4 text-slate-500">{inv.project}</td>
                              <td className="py-3 px-4 text-right font-mono font-medium text-slate-900 tabular-nums">
                                {inv.amountAed}
                              </td>
                              <td className="py-3 px-4">
                                <div className="flex flex-col gap-1 items-start justify-center">
                                  <div>{renderStatus(inv.verificationStatus || inv.status)}</div>
                                  {inv.reviewOutcome && (
                                    <div>{renderReviewStatus(inv.reviewOutcome)}</div>
                                  )}
                                </div>
                              </td>
                              <td className="py-3 px-4 text-[11px]">
                                {inv.hasQuantityMismatch && (
                                  <span className="text-rose-600 font-medium">
                                    Quantity mismatch (D1)
                                  </span>
                                )}
                                {inv.hasMissingEvidence && (
                                  <span className="text-amber-600 font-medium">
                                    Missing evidence (F8)
                                  </span>
                                )}
                                {inv.hasDnReuse && (
                                  <span className="text-blue-600 font-medium">
                                    DN reuse flagged (C1)
                                  </span>
                                )}
                                {!inv.hasQuantityMismatch &&
                                  !inv.hasMissingEvidence &&
                                  !inv.hasDnReuse && (
                                    <span className="text-emerald-600 font-medium">Exact match</span>
                                  )}
                              </td>
                              <td className="py-3 px-4 text-right">
                                <button
                                  onClick={() => {
                                    setSelectedCaseId(inv.id)
                                    setTab('Verify')
                                  }}
                                  className="text-xs font-semibold text-teal-700 hover:text-teal-900 px-2 py-1 rounded hover:bg-teal-50"
                                >
                                  Verify
                                </button>
                              </td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            )}

            {/* TAB: INVOICES (Register View) */}
            {tab === 'Invoices' && (
              <div className="bg-white border border-slate-200 rounded-lg shadow-2xs overflow-hidden">
                <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between bg-slate-50/50">
                  <span className="text-xs font-bold text-slate-900 uppercase tracking-wider">
                    Invoices
                  </span>
                  <div className="flex items-center gap-2 text-xs">
                    <span className="text-slate-400">Filter:</span>
                    <span className="font-semibold text-slate-700">All Cases</span>
                  </div>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-slate-50 border-b border-slate-200 text-slate-600 font-semibold uppercase text-[10px] tracking-wider">
                      <tr>
                        <th className="py-2.5 px-4">Supplier</th>
                        <th className="py-2.5 px-4">Invoice</th>
                        <th className="py-2.5 px-4">Project</th>
                        <th className="py-2.5 px-4">DNs</th>
                        <th className="py-2.5 px-4 text-right">Amount (AED)</th>
                        <th className="py-2.5 px-4">Status</th>
                        <th className="py-2.5 px-4">Rule Notes</th>
                        <th className="py-2.5 px-4 text-right">Action</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100 text-slate-700">
                      {invoices.length === 0 ? (
                        <tr>
                          <td colSpan={8} className="py-8 text-center text-slate-500 text-xs">
                            {isLoading
                              ? 'Loading verification cases from API...'
                              : apiError
                              ? apiError
                              : 'No verification cases available.'}
                          </td>
                        </tr>
                      ) : (
                        invoices.map((inv) => (
                          <tr key={inv.id} className="hover:bg-slate-50/80 transition-colors">
                            <td className="py-3 px-4 font-medium text-slate-900">{inv.supplier}</td>
                            <td className="py-3 px-4 font-mono">{inv.invoiceNo}</td>
                            <td className="py-3 px-4 text-slate-500">{inv.project}</td>
                            <td className="py-3 px-4 text-slate-500 font-mono text-[11px]">
                              {inv.dns.join(', ')}
                            </td>
                            <td className="py-3 px-4 text-right font-mono font-medium text-slate-900 tabular-nums">
                              {inv.amountAed}
                            </td>
                            <td className="py-3 px-4">
                              <div className="flex flex-col gap-1 items-start justify-center">
                                <div>{renderStatus(inv.verificationStatus || inv.status)}</div>
                                {inv.reviewOutcome && (
                                  <div>{renderReviewStatus(inv.reviewOutcome)}</div>
                                )}
                              </div>
                            </td>
                            <td className="py-3 px-4 text-[11px]">
                              {inv.hasQuantityMismatch && (
                                <span className="text-rose-600 font-medium">
                                  Quantity mismatch (D1)
                                </span>
                              )}
                              {inv.hasMissingEvidence && (
                                <span className="text-amber-600 font-medium">
                                  Missing evidence (F8)
                                </span>
                              )}
                              {inv.hasDnReuse && (
                                <span className="text-blue-600 font-medium">
                                  DN reuse flagged (C1)
                                </span>
                              )}
                              {!inv.hasQuantityMismatch &&
                                !inv.hasMissingEvidence &&
                                !inv.hasDnReuse && (
                                  <span className="text-emerald-600 font-medium">Exact match</span>
                                )}
                            </td>
                            <td className="py-3 px-4 text-right">
                              <button
                                onClick={() => {
                                  setSelectedCaseId(inv.id)
                                  setTab('Verify')
                                }}
                                className="text-xs font-semibold text-teal-700 hover:text-teal-900 px-2 py-1 rounded hover:bg-teal-50"
                              >
                                Open
                              </button>
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* TAB: VERIFY (Workspace) */}
            {tab === 'Verify' && (
              !selectedCase ? (
                <div className="bg-white border border-slate-200 rounded-lg p-8 text-center shadow-2xs space-y-2">
                  <AlertTriangle className="w-5 h-5 text-amber-500 mx-auto" />
                  <p className="text-sm font-semibold text-slate-700">No Case Available</p>
                  <p className="text-xs text-slate-500">
                    {apiError
                      ? 'Unable to connect to verification API. Please check server and click Retry above.'
                      : 'Please select or load a verification case.'}
                  </p>
                </div>
              ) : (
              <div className="space-y-6">
                {/* Case Selector Strip */}
                <div className="bg-white border border-slate-200 rounded-lg p-3 shadow-2xs flex items-center justify-between">
                  <div className="flex items-center gap-2 text-xs">
                    <span className="text-slate-500 font-medium">Select Case:</span>
                    <select
                      value={selectedCase.id}
                      onChange={(e) => setSelectedCaseId(e.target.value)}
                      className="border border-slate-300 rounded px-2 py-1 text-xs font-medium text-slate-900 bg-white"
                    >
                      {invoices.map((inv) => (
                        <option key={inv.id} value={inv.id}>
                          {inv.id} — {inv.supplier} ({inv.invoiceNo}) [{inv.status}]
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="text-xs text-slate-400">
                    Rule verification reflects active synthetic case data
                  </div>
                </div>

                {/* Case Header Strip */}
                <div className="bg-white border border-slate-200 rounded-lg p-4 shadow-2xs flex flex-wrap items-center justify-between gap-4">
                  <div className="flex items-center gap-4 text-xs">
                    <div>
                      <span className="text-slate-400 block text-[10px] uppercase">Case</span>
                      <span className="font-bold text-slate-900 font-mono">{selectedCase.id}</span>
                    </div>
                    <div>
                      <span className="text-slate-400 block text-[10px] uppercase">Supplier</span>
                      <span className="font-semibold text-slate-900">{selectedCase.supplier}</span>
                    </div>
                    <div>
                      <span className="text-slate-400 block text-[10px] uppercase">Invoice</span>
                      <span className="font-mono text-slate-700">{selectedCase.invoiceNo}</span>
                    </div>
                    <div>
                      <span className="text-slate-400 block text-[10px] uppercase">Total</span>
                      <span className="font-mono text-slate-900 font-semibold">
                        AED {selectedCase.amountAed}
                      </span>
                    </div>
                    {selectedCase.lpoRef && (
                      <div>
                        <span className="text-slate-400 block text-[10px] uppercase">LPO</span>
                        <span className="font-mono text-slate-700">{selectedCase.lpoRef}</span>
                      </div>
                    )}
                  </div>

                  <div className="flex items-center gap-3">
                    <div className="text-right">
                      <span className="text-[10px] text-slate-400 uppercase block">Verification</span>
                      {renderStatus(selectedCase.verificationStatus || selectedCase.status)}
                    </div>
                    {selectedCase.reviewOutcome && (
                      <div className="text-right">
                        <span className="text-[10px] text-slate-400 uppercase block">Review</span>
                        {renderReviewStatus(selectedCase.reviewOutcome)}
                      </div>
                    )}
                    <button
                      onClick={() => setTab('Review')}
                      className="bg-teal-700 hover:bg-teal-800 text-white text-xs font-semibold px-3 py-1.5 rounded transition-colors"
                    >
                      Review
                    </button>
                  </div>
                </div>

                {/* DN Reuse Alert (Permanent Finding per C1) */}
                {selectedCase.hasDnReuse && selectedCase.dnReuseDetails && (
                  <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 text-xs text-blue-900 space-y-1">
                    <div className="flex items-center gap-2 font-bold text-blue-900">
                      <AlertTriangle className="w-4 h-4 text-blue-600 shrink-0" />
                      <span>PERMANENT AUDIT FINDING: Delivery Note Reuse Detected (Rule C1)</span>
                    </div>
                    <p className="text-blue-800 text-[11px]">
                      Delivery note <span className="font-mono font-semibold">{selectedCase.dnReuseDetails.dnNumber}</span> was previously attached to case{' '}
                      <span className="font-mono font-semibold">{selectedCase.dnReuseDetails.otherCaseId}</span> ({selectedCase.dnReuseDetails.otherCaseStatus}).
                      Under rule C1, this finding is permanent in the audit history. A reviewer may justify reuse with mandatory notes, permitting at most "Verified with noted exceptions".
                    </p>
                  </div>
                )}

                {/* Document Upload Widget */}
                <div className="bg-white border border-slate-200 rounded-lg p-4 shadow-2xs space-y-3">
                  <div className="flex items-center justify-between border-b border-slate-100 pb-2">
                    <div className="flex items-center gap-2 text-xs font-bold text-slate-900 uppercase tracking-wider">
                      <Upload className="w-3.5 h-3.5 text-teal-600" />
                      <span>Attach Document to Case</span>
                    </div>
                    <span className="text-[10px] text-slate-400 font-mono">
                      FastAPI Storage • Synthetic Files Only
                    </span>
                  </div>

                  {uploadError && (
                    <div className="p-3 bg-rose-50 border border-rose-200 rounded-md text-rose-900 text-xs flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <XCircle className="w-4 h-4 text-rose-600 shrink-0" />
                        <span>{uploadError}</span>
                      </div>
                      <button onClick={() => setUploadError(null)} className="text-rose-500 hover:text-rose-700">
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  )}

                  {uploadWarning && (
                    <div className="p-3 bg-blue-50 border border-blue-200 rounded-md text-blue-900 text-xs flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <AlertTriangle className="w-4 h-4 text-blue-600 shrink-0" />
                        <span>{uploadWarning}</span>
                      </div>
                      <button onClick={() => setUploadWarning(null)} className="text-blue-500 hover:text-blue-700">
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  )}

                  <form onSubmit={handleUploadDocument} className="flex flex-wrap items-center gap-3 text-xs">
                    <div className="flex items-center gap-2">
                      <label className="font-medium text-slate-600">Document Type:</label>
                      <select
                        value={uploadDocType}
                        onChange={(e) => setUploadDocType(e.target.value as 'DELIVERY_NOTE' | 'INVOICE' | 'LPO')}
                        className="border border-slate-300 rounded px-2.5 py-1.5 bg-white text-slate-900 text-xs font-medium"
                      >
                        <option value="DELIVERY_NOTE">Delivery Note</option>
                        <option value="INVOICE">Supplier Invoice</option>
                        <option value="LPO">Local Purchase Order (LPO)</option>
                      </select>
                    </div>

                    <div className="flex-1 min-w-[200px]">
                      <input
                        id="doc-file-input"
                        type="file"
                        accept=".pdf,.jpg,.jpeg,.png"
                        onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
                        className="text-xs text-slate-600 file:mr-2 file:py-1.5 file:px-3 file:rounded file:border-0 file:text-xs file:font-semibold file:bg-slate-100 file:text-slate-700 hover:file:bg-slate-200 cursor-pointer"
                      />
                    </div>

                    <button
                      type="submit"
                      disabled={isUploading || !uploadFile}
                      className={`px-3 py-1.5 rounded text-xs font-semibold flex items-center gap-1.5 transition-colors ${
                        isUploading || !uploadFile
                          ? 'bg-slate-200 text-slate-400 cursor-not-allowed'
                          : 'bg-teal-700 hover:bg-teal-800 text-white shadow-xs'
                      }`}
                    >
                      <Upload className="w-3.5 h-3.5" />
                      <span>{isUploading ? 'Uploading...' : 'Upload Document'}</span>
                    </button>
                  </form>
                </div>

                {/* Split Document Viewers */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {/* Left: Invoice Panel */}
                  <div className="bg-white border border-slate-200 rounded-lg p-4 shadow-2xs space-y-3">
                    <div className="flex items-center justify-between border-b border-slate-100 pb-2">
                      <div className="flex items-center gap-2 text-xs font-semibold text-slate-900">
                        <FileText className="w-3.5 h-3.5 text-slate-500" />
                        <span>Invoice Document</span>
                      </div>
                      <span className="font-mono text-[11px] text-slate-400">
                        {selectedCase.invoiceNo}.pdf
                      </span>
                    </div>
                    <div className="bg-slate-50 border border-dashed border-slate-200 rounded p-4 text-center text-xs text-slate-500 space-y-1">
                      <p className="font-semibold text-slate-700">{selectedCase.supplier}</p>
                      <p className="font-mono text-[11px]">TRN: {selectedCase.supplierTrn}</p>
                      <div className="pt-2 text-[11px] text-slate-400">
                        Project: {selectedCase.project} • Invoiced Total: AED {selectedCase.amountAed}
                      </div>
                    </div>

                    {/* Attached Invoice Files */}
                    {selectedCase.documents?.filter((d) => d.doc_type === 'INVOICE').length ? (
                      <div className="space-y-1.5 pt-1">
                        <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider block">
                          Attached Invoices ({selectedCase.documents.filter((d) => d.doc_type === 'INVOICE').length})
                        </span>
                        {selectedCase.documents
                          .filter((d) => d.doc_type === 'INVOICE')
                          .map((doc) => (
                            <div
                              key={doc.id}
                              className="flex items-center justify-between p-2 bg-slate-50 rounded border border-slate-200 text-xs"
                            >
                              <div className="flex items-center gap-2 truncate">
                                <FileText className="w-3.5 h-3.5 text-slate-600 shrink-0" />
                                <span className="font-mono text-slate-800 truncate">
                                  {doc.original_filename}
                                </span>
                              </div>
                              <a
                                href={getDocumentContentUrl(doc.id)}
                                target="_blank"
                                rel="noreferrer"
                                className="inline-flex items-center gap-1 text-[11px] text-teal-700 hover:text-teal-900 font-medium shrink-0 ml-2"
                              >
                                <ExternalLink className="w-3 h-3" />
                                <span>Preview</span>
                              </a>
                            </div>
                          ))}
                      </div>
                    ) : null}
                  </div>

                  {/* Right: Delivery Note Panel */}
                  <div className="bg-white border border-slate-200 rounded-lg p-4 shadow-2xs space-y-3">
                    <div className="flex items-center justify-between border-b border-slate-100 pb-2">
                      <div className="flex items-center gap-2 text-xs font-semibold text-slate-900">
                        <FileCheck2 className="w-3.5 h-3.5 text-teal-600" />
                        <span>Delivery Note</span>
                      </div>
                      <span className="font-mono text-[11px] text-slate-400">
                        {selectedCase.dns.join(' / ')}
                      </span>
                    </div>
                    <div className="bg-slate-50 border border-dashed border-slate-200 rounded p-4 text-center text-xs text-slate-500 space-y-1">
                      <p className="font-semibold text-slate-700">Site Ticket Verification</p>
                      <p className="font-mono text-[11px]">
                        {selectedCase.project} • Received {selectedCase.date}
                      </p>
                      <div className="pt-2 text-[11px] text-slate-400">
                        Attached Tickets: {selectedCase.dns.join(', ')}
                      </div>
                    </div>

                    {/* Attached Delivery Note Files */}
                    {selectedCase.documents?.filter((d) => d.doc_type === 'DELIVERY_NOTE').length ? (
                      <div className="space-y-1.5 pt-1">
                        <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider block">
                          Attached Delivery Notes ({selectedCase.documents.filter((d) => d.doc_type === 'DELIVERY_NOTE').length})
                        </span>
                        {selectedCase.documents
                          .filter((d) => d.doc_type === 'DELIVERY_NOTE')
                          .map((doc) => (
                            <div
                              key={doc.id}
                              className="flex items-center justify-between p-2 bg-slate-50 rounded border border-slate-200 text-xs"
                            >
                              <div className="flex items-center gap-2 truncate">
                                <FileCheck2 className="w-3.5 h-3.5 text-teal-600 shrink-0" />
                                <span className="font-mono text-slate-800 truncate">
                                  {doc.original_filename}
                                </span>
                              </div>
                              <a
                                href={getDocumentContentUrl(doc.id)}
                                target="_blank"
                                rel="noreferrer"
                                className="inline-flex items-center gap-1 text-[11px] text-teal-700 hover:text-teal-900 font-medium shrink-0 ml-2"
                              >
                                <ExternalLink className="w-3 h-3" />
                                <span>Preview</span>
                              </a>
                            </div>
                          ))}
                      </div>
                    ) : null}
                  </div>
                </div>

                {/* Line Item Reconciliation Table */}
                <div className="bg-white border border-slate-200 rounded-lg shadow-2xs overflow-hidden">
                  <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between bg-slate-50/50">
                    <span className="text-xs font-bold text-slate-900 uppercase tracking-wider">
                      Line Comparison
                    </span>
                    <span className="text-[11px] font-mono text-slate-400">
                      Exact Quantity Match (D1 Zero Tolerance)
                    </span>
                  </div>

                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-xs min-w-[640px]">
                      <thead className="bg-slate-50 border-b border-slate-200 text-slate-600 font-semibold uppercase text-[10px] tracking-wider">
                        <tr>
                          <th className="py-2.5 px-4">Item</th>
                          <th className="py-2.5 px-4 text-right">Invoiced Qty</th>
                          <th className="py-2.5 px-4 text-right">Delivered Qty</th>
                          <th className="py-2.5 px-4 text-right">Exact Diff</th>
                          <th className="py-2.5 px-4">Unit</th>
                          <th className="py-2.5 px-4">Reference</th>
                          <th className="py-2.5 px-4">Rule Status</th>
                          <th className="py-2.5 px-4">Status</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100 text-slate-700">
                        {selectedCase.lines.map((row, idx) => (
                          <tr
                            key={idx}
                            className={
                              row.status === 'Mismatch'
                                ? 'bg-rose-50/40'
                                : row.status === 'Missing'
                                ? 'bg-amber-50/40'
                                : 'hover:bg-slate-50/80 transition-colors'
                            }
                          >
                            <td className="py-3 px-4 font-medium text-slate-900">{row.item}</td>
                            <td className="py-3 px-4 text-right font-mono tabular-nums">
                              {row.invQty}
                            </td>
                            <td className="py-3 px-4 text-right font-mono tabular-nums">
                              {row.dnQty}
                            </td>
                            <td
                              className={`py-3 px-4 text-right font-mono font-semibold tabular-nums ${
                                row.diff !== '0.000' && row.diff !== '—'
                                  ? 'text-rose-600'
                                  : 'text-slate-600'
                              }`}
                            >
                              {row.diff}
                            </td>
                            <td className="py-3 px-4 font-mono text-slate-600">
                              {row.unit || '—'}
                            </td>
                            <td className="py-3 px-4 font-mono text-slate-500 text-[11px]">
                              {row.dnRef}
                            </td>
                            <td className="py-3 px-4">
                              <span className="font-mono text-[10px] bg-slate-100 text-slate-700 px-1.5 py-0.5 rounded border border-slate-200">
                                {row.ruleStatus || 'CONFIRMED'}
                              </span>
                            </td>
                            <td className="py-3 px-4">{renderStatus(row.status)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            ))}

            {/* TAB: REVIEW (Sign-off) */}
            {tab === 'Review' && (
              !selectedCase ? (
                <div className="bg-white border border-slate-200 rounded-lg p-8 text-center shadow-2xs space-y-2">
                  <AlertTriangle className="w-5 h-5 text-amber-500 mx-auto" />
                  <p className="text-sm font-semibold text-slate-700">No Case Available</p>
                  <p className="text-xs text-slate-500">
                    {apiError
                      ? 'Unable to connect to verification API. Please check server and click Retry above.'
                      : 'Please select or load a verification case.'}
                  </p>
                </div>
              ) : (
              <div className="bg-white border border-slate-200 rounded-lg p-6 shadow-2xs space-y-6 max-w-2xl mx-auto">
                <div className="border-b border-slate-100 pb-3 flex items-center justify-between">
                  <div>
                    <h3 className="text-sm font-bold text-slate-900 uppercase tracking-wider">
                      Review & Sign-Off
                    </h3>
                    <p className="text-xs text-slate-500 mt-0.5">
                      Case {selectedCase.id} • {selectedCase.supplier} • {selectedCase.invoiceNo}
                    </p>
                  </div>
                  <div className="text-right">
                    <span className="text-[10px] text-slate-400 uppercase block">Active Status</span>
                    {renderStatus(selectedCase.status)}
                  </div>
                </div>

                {/* Safety Warning */}
                <div className="p-3 bg-amber-50 border border-amber-200 rounded-md text-amber-900 text-xs flex items-center gap-2">
                  <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0" />
                  <span>
                    Mandatory Human Review Required. The system records audit sign-offs only and never initiates disbursements or payment approvals.
                  </span>
                </div>

                {/* Validation Error Banner */}
                {reviewValidationError && (
                  <div className="p-3 bg-rose-50 border border-rose-200 rounded-md text-rose-900 text-xs flex items-center gap-2">
                    <XCircle className="w-4 h-4 text-rose-600 shrink-0" />
                    <span>{reviewValidationError}</span>
                  </div>
                )}

                <div className="space-y-5">
                  {/* Review Outcome Selection */}
                  <div>
                    <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1.5">
                      Review Outcome
                    </label>
                    <select
                      value={selectedOutcome}
                      onChange={(e) => setSelectedOutcome(e.target.value as ReviewOutcome)}
                      className="w-full text-xs border border-slate-300 rounded p-2.5 bg-white text-slate-900 font-medium"
                    >
                      {permittedOutcomes.map((opt) => (
                        <option
                          key={opt.value}
                          value={opt.value}
                          disabled={!opt.allowed}
                          className={opt.allowed ? 'text-slate-900' : 'text-slate-400 bg-slate-100'}
                        >
                          {formatOutcomeOptionLabel(opt)}
                        </option>
                      ))}
                    </select>

                    {/* Explanatory notice when options are restricted */}
                    {selectedCase.hasQuantityMismatch && (
                      <p className="text-[11px] text-rose-600 mt-1.5 font-medium flex items-center gap-1">
                        <Lock className="w-3 h-3" />
                        "Verified with noted exceptions" is prevented: Quantity discrepancies must be queried or rejected under D1 zero-tolerance.
                      </p>
                    )}
                    {selectedCase.hasMissingEvidence && (
                      <p className="text-[11px] text-amber-600 mt-1.5 font-medium flex items-center gap-1">
                        <Lock className="w-3 h-3" />
                        "Verified with noted exceptions" is prevented: Missing required evidence must be queried or rejected under F8.
                      </p>
                    )}
                    {selectedCase.hasDnReuse && (
                      <p className="text-[11px] text-blue-600 mt-1.5 font-medium flex items-center gap-1">
                        <Info className="w-3 h-3" />
                        "Verified with noted exceptions" permitted for justified DN reuse (Rule C1). Reviewer justification required.
                      </p>
                    )}
                  </div>

                  {/* Manual VAT Check Documented (C4 / P9) */}
                  <div className="bg-slate-50 border border-slate-200 rounded-md p-3.5 space-y-2">
                    <div className="flex items-start gap-2.5">
                      <input
                        type="checkbox"
                        id="vat-manual-check"
                        checked={manualVatChecked}
                        onChange={(e) => setManualVatChecked(e.target.checked)}
                        className="mt-0.5 rounded border-slate-300 text-teal-600 focus:ring-teal-500"
                      />
                      <label htmlFor="vat-manual-check" className="text-xs text-slate-800">
                        <span className="font-semibold block">Document Manual VAT Check (UAE 5%)</span>
                        <span className="text-[11px] text-slate-500 block mt-0.5">
                          Reviewer checked stated 5% rate, taxable amount, and supplier TRN.
                        </span>
                      </label>
                    </div>
                    <div className="text-[10px] text-slate-500 border-t border-slate-200 pt-1.5 font-mono">
                      Automated VAT Status: <span className="font-semibold text-slate-700">NOT_CHECKED</span> (Rule pack pending M14). Recording manual check does not imply automated verification.
                    </div>
                  </div>

                  {/* Reviewer Justification & Notes */}
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider">
                        Reviewer Justification / Notes
                      </label>
                      <span className="text-[10px] text-slate-400">
                        {selectedOutcome === 'VERIFIED_WITH_EXCEPTIONS'
                          ? 'Mandatory (min 10 chars)'
                          : selectedOutcome === 'ON_HOLD_QUERIED' || selectedOutcome === 'REJECTED'
                          ? 'Mandatory (min 5 chars)'
                          : 'Optional'}
                      </span>
                    </div>
                    <textarea
                      rows={3}
                      value={reviewerNote}
                      onChange={(e) => setReviewerNote(e.target.value)}
                      placeholder={
                        selectedOutcome === 'VERIFIED_WITH_EXCEPTIONS'
                          ? 'State why the permitted exception (e.g. DN reuse) is acceptable...'
                          : selectedOutcome === 'ON_HOLD_QUERIED'
                          ? 'State question or query to supplier...'
                          : selectedOutcome === 'REJECTED'
                          ? 'State reason for rejecting invoice back to supplier...'
                          : 'Record review remarks...'
                      }
                      className="w-full text-xs border border-slate-300 rounded p-2.5 text-slate-900 placeholder:text-slate-400 focus:outline-teal-600"
                    />
                  </div>

                  {/* Mandatory Safety Declaration */}
                  <div className="border border-slate-200 rounded-md p-3.5 bg-slate-50/50">
                    <label className="flex items-start gap-3 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={declarationAccepted}
                        onChange={(e) => setDeclarationAccepted(e.target.checked)}
                        className="mt-0.5 rounded border-slate-300 text-teal-600 focus:ring-teal-500"
                      />
                      <span className="text-xs text-slate-700 leading-relaxed">
                        <strong className="text-slate-900 block font-semibold mb-1">
                          Mandatory Audit Declaration
                        </strong>
                        I declare that I have reviewed the source documents, delivery tickets, and comparison findings. Any VAT review was performed manually. This record is an audit sign-off only and does not approve or execute payments.
                      </span>
                    </label>
                  </div>

                  {/* Actions */}
                  <div className="pt-2 flex items-center justify-end gap-2 border-t border-slate-100">
                    <button
                      onClick={() => setTab('Verify')}
                      className="px-3 py-1.5 text-xs font-medium text-slate-600 hover:text-slate-900 rounded"
                    >
                      Cancel
                    </button>
                    <button
                      onClick={handleSaveReview}
                      disabled={!isReviewSubmittable || isSubmittingReview}
                      className={`px-4 py-2 text-xs font-semibold rounded-md shadow-xs transition-colors ${
                        !isReviewSubmittable || isSubmittingReview
                          ? 'bg-slate-200 text-slate-400 cursor-not-allowed'
                          : 'bg-slate-900 hover:bg-slate-800 text-white'
                      }`}
                    >
                      {isSubmittingReview ? 'Recording Decision...' : 'Record Review Decision'}
                    </button>
                  </div>
                </div>
              </div>
            ))}

            {/* TAB: HISTORY (Audit Trail) */}
            {tab === 'History' && (
              !selectedCase ? (
                <div className="bg-white border border-slate-200 rounded-lg p-8 text-center shadow-2xs space-y-2">
                  <AlertTriangle className="w-5 h-5 text-amber-500 mx-auto" />
                  <p className="text-sm font-semibold text-slate-700">No Case Available</p>
                  <p className="text-xs text-slate-500">
                    {apiError
                      ? 'Unable to connect to verification API. Please check server and click Retry above.'
                      : 'Please select or load a verification case.'}
                  </p>
                </div>
              ) : (
              <div className="bg-white border border-slate-200 rounded-lg p-6 shadow-2xs space-y-4 max-w-2xl mx-auto">
                <div className="border-b border-slate-100 pb-3 flex items-center justify-between">
                  <div>
                    <span className="text-xs font-bold text-slate-900 uppercase tracking-wider">
                      Case Audit History
                    </span>
                    <p className="text-[11px] text-slate-500 mt-0.5">
                      Case: <span className="font-mono font-semibold">{selectedCase.id}</span> • {selectedCase.supplier}
                    </p>
                  </div>
                  <span className="text-[11px] text-slate-400 font-mono">Append-Only Trail</span>
                </div>

                <div className="space-y-3 text-xs">
                  {selectedCase.auditHistory.map((item) => (
                    <div
                      key={item.id}
                      className={`flex items-start gap-3 p-3 rounded border ${
                        item.permanent || item.type === 'DN_REUSE'
                          ? 'bg-blue-50/70 border-blue-200'
                          : item.type === 'REVIEW'
                          ? 'bg-teal-50/70 border-teal-200'
                          : 'bg-white border-slate-100 hover:bg-slate-50'
                      }`}
                    >
                      <div
                        className={`w-2 h-2 rounded-full mt-1.5 shrink-0 ${
                          item.permanent || item.type === 'DN_REUSE'
                            ? 'bg-blue-600'
                            : item.type === 'REVIEW'
                            ? 'bg-teal-600'
                            : item.type === 'RUN'
                            ? 'bg-slate-700'
                            : 'bg-slate-400'
                        }`}
                      />
                      <div className="flex-1 space-y-0.5">
                        <div className="flex items-center justify-between">
                          <span className="font-semibold text-slate-900">{item.title}</span>
                          <span className="text-[11px] text-slate-400 font-mono">{item.time}</span>
                        </div>
                        <div className="text-[11px] text-slate-600">{item.detail}</div>
                        {(item.permanent || item.type === 'DN_REUSE') && (
                          <div className="pt-1">
                            <span className="text-[9px] uppercase font-bold tracking-wider px-1.5 py-0.5 rounded bg-blue-200 text-blue-900 font-mono">
                              Permanent Finding (Rule C1)
                            </span>
                          </div>
                        )}
                        <div className="text-[10px] text-slate-400 font-mono">Actor: {item.actor}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}

            {/* TAB: SETTINGS (Technical Specs & Guardrails) */}
            {tab === 'Settings' && (
              <div className="space-y-6">
                <div className="border-b border-slate-200 pb-2 flex items-center justify-between">
                  <h3 className="text-sm font-bold text-slate-900 uppercase tracking-wider">
                    Settings & Policies
                  </h3>
                  <span className="text-xs text-slate-500">
                    API Status:{' '}
                    {ruleset ? (
                      <span className="text-emerald-600 font-semibold font-mono">
                        Online (HTTPS Gateway)
                      </span>
                    ) : (
                      <span className="text-rose-500 font-semibold">Offline</span>
                    )}
                  </span>
                </div>

                {/* Mandatory Review Policy Banner */}
                <div className="bg-slate-900 text-white rounded-lg p-4 flex items-center justify-between shadow-xs">
                  <div className="flex items-center gap-3">
                    <ShieldCheck className="w-5 h-5 text-teal-400" />
                    <div className="text-xs">
                      <div className="font-bold text-white">Human Review Required</div>
                      <div className="text-slate-400 text-[11px]">
                        The system never automatically approves invoices or initiates disbursements.
                      </div>
                    </div>
                  </div>
                  <span className="text-[10px] bg-slate-800 text-teal-300 px-2 py-0.5 rounded font-mono uppercase">
                    Enforced
                  </span>
                </div>

                {/* Policies Grid */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
                  <div className="bg-white border border-slate-200 rounded-lg p-4 space-y-1">
                    <div className="flex items-center justify-between font-semibold text-slate-900">
                      <span>Quantity Zero Tolerance (D1)</span>
                      <span className="text-[10px] bg-emerald-100 text-emerald-800 px-1.5 py-0.5 rounded font-mono">
                        CONFIRMED
                      </span>
                    </div>
                    <p className="text-slate-500 text-[11px]">
                      Exact Decimal comparison. Zero tolerance. Never rounded.
                    </p>
                  </div>

                  <div className="bg-white border border-slate-200 rounded-lg p-4 space-y-1">
                    <div className="flex items-center justify-between font-semibold text-slate-900">
                      <span>Accepted Delivery Quantity (D2)</span>
                      <span className="text-[10px] bg-emerald-100 text-emerald-800 px-1.5 py-0.5 rounded font-mono">
                        CONFIRMED
                      </span>
                    </div>
                    <p className="text-slate-500 text-[11px]">
                      Reconciliation uses accepted delivered quantity, excluding documented rejections.
                    </p>
                  </div>

                  <div className="bg-white border border-slate-200 rounded-lg p-4 space-y-1">
                    <div className="flex items-center justify-between font-semibold text-slate-900">
                      <span>Financial Rounding (P1)</span>
                      <span className="text-[10px] bg-amber-100 text-amber-800 px-1.5 py-0.5 rounded font-mono">
                        PROVISIONAL
                      </span>
                    </div>
                    <p className="text-slate-500 text-[11px]">
                      Computed financial values rounded 2 decimal places (fils, ROUND_HALF_UP).
                    </p>
                  </div>

                  <div className="bg-white border border-slate-200 rounded-lg p-4 space-y-1">
                    <div className="flex items-center justify-between font-semibold text-slate-900">
                      <span>Line Matching Multiplicity (P2)</span>
                      <span className="text-[10px] bg-amber-100 text-amber-800 px-1.5 py-0.5 rounded font-mono">
                        PROVISIONAL
                      </span>
                    </div>
                    <p className="text-slate-500 text-[11px]">
                      One invoice line links to one delivery note line in prototype.
                    </p>
                  </div>

                  <div className="bg-white border border-slate-200 rounded-lg p-4 space-y-1">
                    <div className="flex items-center justify-between font-semibold text-slate-900">
                      <span>DN Reuse Rule (D3/C1)</span>
                      <span className="text-[10px] bg-blue-100 text-blue-800 px-1.5 py-0.5 rounded font-mono">
                        CONFIRMED
                      </span>
                    </div>
                    <p className="text-slate-500 text-[11px]">
                      One invoice per delivery note. Reuse permanently flagged in audit trail.
                    </p>
                  </div>

                  <div className="bg-white border border-slate-200 rounded-lg p-4 space-y-1">
                    <div className="flex items-center justify-between font-semibold text-slate-900">
                      <span>Mandatory LPO Requirement (D4)</span>
                      <span className="text-[10px] bg-emerald-100 text-emerald-800 px-1.5 py-0.5 rounded font-mono">
                        CONFIRMED
                      </span>
                    </div>
                    <p className="text-slate-500 text-[11px]">
                      LPO required unless explicitly waived with recorded reason code.
                    </p>
                  </div>

                  <div className="bg-white border border-slate-200 rounded-lg p-4 space-y-1">
                    <div className="flex items-center justify-between font-semibold text-slate-900">
                      <span>Automated VAT (D5/C4)</span>
                      <span className="text-[10px] bg-slate-200 text-slate-800 px-1.5 py-0.5 rounded font-mono">
                        NOT_CHECKED
                      </span>
                    </div>
                    <p className="text-slate-500 text-[11px]">
                      Automated validation gated pending M14. Manual check documentation permitted (P9).
                    </p>
                  </div>

                  <div className="bg-white border border-slate-200 rounded-lg p-4 space-y-1">
                    <div className="flex items-center justify-between font-semibold text-slate-900">
                      <span>Reviewer Role Authorization (D6)</span>
                      <span className="text-[10px] bg-emerald-100 text-emerald-800 px-1.5 py-0.5 rounded font-mono">
                        CONFIRMED
                      </span>
                    </div>
                    <p className="text-slate-500 text-[11px]">
                      Only authorized users (can_review=True) may record formal review decisions.
                    </p>
                  </div>
                </div>
              </div>
            )}
          </div>
        </main>
      </div>

      {/* Consistent Create Case Workflow Placeholder Modal (M2 Boundary) */}
      {createWorkflow.isModalOpen && (
        <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white border border-slate-200 rounded-xl shadow-xl max-w-lg w-full overflow-hidden animate-fade-in">
            {/* Modal Header */}
            <div className="bg-slate-900 text-white px-5 py-4 flex items-center justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <h3 className="text-sm font-bold uppercase tracking-wider">
                    Create Verification Case
                  </h3>
                  <span className="bg-amber-500/20 text-amber-300 text-[10px] font-mono px-2 py-0.5 rounded border border-amber-500/30">
                    Creation Disabled
                  </span>
                </div>
                <p className="text-xs text-slate-400 mt-0.5">
                  Workflow Preview (Case Creation Disabled)
                </p>
              </div>
              <button
                onClick={() => setCreateWorkflow(closeCreateWorkflow(createWorkflow))}
                className="text-slate-400 hover:text-white transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Modal Body */}
            <div className="p-6 space-y-5 text-xs text-slate-600">
              {/* Notice */}
              <div className="p-3 bg-amber-50 border border-amber-200 rounded-lg text-amber-900 space-y-1">
                <div className="flex items-center gap-1.5 font-bold">
                  <Info className="w-4 h-4 text-amber-600 shrink-0" />
                  <span>Workflow Boundary Notice</span>
                </div>
                <p className="text-[11px] leading-relaxed">
                  {createWorkflow.message}
                </p>
              </div>

              {/* Wizard Steps Preview (Disabled) */}
              <div className="space-y-2.5">
                <div className="font-semibold text-slate-900 uppercase text-[10px] tracking-wider">
                  Future Case-Creation Workflow
                </div>

                <div className="border border-slate-200 rounded-lg divide-y divide-slate-100 bg-slate-50/50">
                  <div className="p-2.5 flex items-center justify-between opacity-60">
                    <span className="font-medium text-slate-800">1. Case Details & LPO Requirement</span>
                    <span className="text-[10px] font-mono text-slate-500">Project / Supplier / LPO Reason</span>
                  </div>
                  <div className="p-2.5 flex items-center justify-between opacity-60">
                    <span className="font-medium text-slate-800">2. Supplier Invoice Upload</span>
                    <span className="text-[10px] font-mono text-slate-500">PDF / Image validation</span>
                  </div>
                  <div className="p-2.5 flex items-center justify-between opacity-60">
                    <span className="font-medium text-slate-800">3. Delivery Notes Multi-Upload</span>
                    <span className="text-[10px] font-mono text-slate-500">DN Reuse & duplicate checks</span>
                  </div>
                  <div className="p-2.5 flex items-center justify-between opacity-60">
                    <span className="font-medium text-slate-800">4. Summary & Review Assignment</span>
                    <span className="text-[10px] font-mono text-slate-500">Audit trail initialization</span>
                  </div>
                </div>
              </div>

              <div className="text-[11px] text-slate-500 bg-slate-100 p-2.5 rounded font-mono">
                Safe Prototype Guard: Real supplier documents are strictly prohibited. New case creation is disabled to preserve synthetic-only isolation.
              </div>
            </div>

            {/* Modal Footer */}
            <div className="bg-slate-50 border-t border-slate-200 px-6 py-3 flex items-center justify-end gap-2">
              <button
                disabled
                className="px-3.5 py-1.5 text-xs font-medium bg-slate-200 text-slate-400 rounded cursor-not-allowed"
              >
                Case Creation Disabled
              </button>
              <button
                onClick={() => setCreateWorkflow(closeCreateWorkflow(createWorkflow))}
                className="px-4 py-1.5 text-xs font-semibold bg-slate-900 hover:bg-slate-800 text-white rounded transition-colors"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Pilot Login Modal */}
      {isLoginModalOpen && (
        <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white border border-slate-200 rounded-xl shadow-xl max-w-md w-full overflow-hidden animate-fade-in">
            <div className="bg-slate-900 text-white px-5 py-4 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Lock className="w-4 h-4 text-teal-400" />
                <h3 className="text-sm font-bold uppercase tracking-wider">Pilot Sign In</h3>
              </div>
              <button
                onClick={() => setIsLoginModalOpen(false)}
                className="text-slate-400 hover:text-white transition-colors cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-6 space-y-4">
              <p className="text-xs text-slate-500">
                Authenticate with a provisioned pilot account to access case verification records and review workflows. Pilot credentials are provisioned locally.
              </p>

              {/* Quick Select Quickfill */}
              <div className="space-y-1.5">
                <label className="text-[11px] font-semibold text-slate-700 uppercase tracking-wider">
                  Quick Select Pilot Account
                </label>
                <div className="grid grid-cols-2 gap-2">
                  {PILOT_ACCOUNTS.map((acc) => (
                    <button
                      key={acc.email}
                      type="button"
                      onClick={() => {
                        setLoginEmail(acc.email)
                        setLoginPassword('')
                        setLoginError(null)
                      }}
                      className="text-left p-2 rounded border border-slate-200 hover:border-teal-500 hover:bg-teal-50/40 transition-colors text-xs cursor-pointer"
                    >
                      <div className="font-semibold text-slate-900">{acc.role}</div>
                      <div className="text-[10px] text-slate-500 truncate">{acc.name}</div>
                    </button>
                  ))}
                </div>
              </div>

              <form onSubmit={handleLogin} className="space-y-3 pt-2">
                <div>
                  <label className="block text-xs font-medium text-slate-700 mb-1">
                    Email / Username
                  </label>
                  <input
                    type="text"
                    required
                    value={loginEmail}
                    onChange={(e) => setLoginEmail(e.target.value)}
                    className="w-full text-xs px-3 py-2 border border-slate-300 rounded-md focus:outline-none focus:ring-1 focus:ring-teal-500"
                    placeholder="user@pilot.civ.local"
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-slate-700 mb-1">
                    Password
                  </label>
                  <input
                    type="password"
                    required
                    value={loginPassword}
                    onChange={(e) => setLoginPassword(e.target.value)}
                    className="w-full text-xs px-3 py-2 border border-slate-300 rounded-md focus:outline-none focus:ring-1 focus:ring-teal-500"
                    placeholder="Enter locally provisioned password"
                  />
                </div>

                {loginError && (
                  <div className="p-2.5 bg-rose-50 border border-rose-200 rounded text-rose-700 text-xs flex items-center gap-2">
                    <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                    <span>{loginError}</span>
                  </div>
                )}

                <div className="pt-2 flex items-center justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => setIsLoginModalOpen(false)}
                    className="px-3 py-1.5 text-xs text-slate-600 hover:text-slate-900 cursor-pointer"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={isLoggingIn}
                    className="px-4 py-1.5 text-xs font-semibold bg-teal-600 hover:bg-teal-700 text-white rounded shadow-xs disabled:opacity-50 flex items-center gap-1.5 cursor-pointer"
                  >
                    {isLoggingIn && <RefreshCw className="w-3 h-3 animate-spin" />}
                    <span>{isLoggingIn ? 'Signing In...' : 'Sign In'}</span>
                  </button>
                </div>
              </form>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default App
