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
  Link2,
  Layers,
  Sparkles,
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
  canCreateCase,
  validateDecimal,
  validateCaseRef,
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
  fetchProjects,
  fetchSuppliers,
  fetchLpos,
  createCase,
  addInvoiceLine,
  addDnLine,
  createLineLink,
  runVerification,
  triggerExtraction,
  fetchDocumentFields,
  updateExtractedField,
  confirmDocumentFields,
  ApiError,
  type ApiCaseDetail,
  type UserProfile,
  type ApiProject,
  type ApiSupplier,
  type ApiLpoSummary,
  type ApiDocumentFieldsResponse,
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
    desc: 'Quantity Surveyor (Data Entry & Reconciliation)',
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
  {
    role: 'Commercial Director',
    name: 'Khalfan Director',
    email: 'khalfan.director@pilot.civ.local',
    desc: 'Commercial Director (Admin)',
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
  
  // Reference data state
  const [projectsList, setProjectsList] = useState<ApiProject[]>([])
  const [suppliersList, setSuppliersList] = useState<ApiSupplier[]>([])
  const [lposList, setLposList] = useState<ApiLpoSummary[]>([])

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

  // Create case workflow & form state
  const [createWorkflow, setCreateWorkflow] = useState(INITIAL_CREATE_WORKFLOW_STATE)
  const [createCaseRef, setCreateCaseRef] = useState('')
  const [createProjectId, setCreateProjectId] = useState('')
  const [createSupplierId, setCreateSupplierId] = useState('')
  const [createInvoiceHint, setCreateInvoiceHint] = useState('')
  const [createLpoRequired, setCreateLpoRequired] = useState(true)
  const [createLpoId, setCreateLpoId] = useState('')
  const [isSubmittingCase, setIsSubmittingCase] = useState(false)
  const [createCaseError, setCreateCaseError] = useState<string | null>(null)

  // Step 4 manual data entry workspace state
  const [dataEntryTab, setDataEntryTab] = useState<'invoice' | 'dn' | 'links'>('invoice')

  // Invoice line entry state
  const [invLineNo, setInvLineNo] = useState(1)
  const [invDescription, setInvDescription] = useState('')
  const [invQty, setInvQty] = useState('')
  const [invUnit, setInvUnit] = useState('m3')
  const [invUnitPrice, setInvUnitPrice] = useState('')
  const [invLineAmount, setInvLineAmount] = useState('')
  const [isAddingInvLine, setIsAddingInvLine] = useState(false)
  const [invLineError, setInvLineError] = useState<string | null>(null)

  // Delivery Note line entry state
  const [dnNumber, setDnNumber] = useState('')
  const [dnLineNo, setDnLineNo] = useState(1)
  const [dnDescription, setDnDescription] = useState('')
  const [dnDeliveredQty, setDnDeliveredQty] = useState('')
  const [dnUnit, setDnUnit] = useState('m3')
  const [dnStoreTicket, setDnStoreTicket] = useState('')
  const [dnStoreConfirmed, setDnStoreConfirmed] = useState(true)
  const [dnRejectedQty, setDnRejectedQty] = useState('')
  const [dnRejectionReason, setDnRejectionReason] = useState('')
  const [dnHasRejectionEvidence, setDnHasRejectionEvidence] = useState(false)
  const [isAddingDnLine, setIsAddingDnLine] = useState(false)
  const [dnLineError, setDnLineError] = useState<string | null>(null)

  // Line linking state
  const [linkInvLineId, setLinkInvLineId] = useState('')
  const [linkDnLineId, setLinkDnLineId] = useState('')
  const [linkLpoLineId, setLinkLpoLineId] = useState('')
  const [isLinking, setIsLinking] = useState(false)
  const [linkError, setLinkError] = useState<string | null>(null)

  // Verification execution state
  const [isRunningVerification, setIsRunningVerification] = useState(false)
  const [verifyError, setVerifyError] = useState<string | null>(null)
  const [verifySuccess, setVerifySuccess] = useState<string | null>(null)

  // Auth & Login modal state
  const [isLoginModalOpen, setIsLoginModalOpen] = useState(false)
  const [loginEmail, setLoginEmail] = useState('')
  const [loginPassword, setLoginPassword] = useState('')
  const [loginError, setLoginError] = useState<string | null>(null)
  const [isLoggingIn, setIsLoggingIn] = useState(false)

  // AI Document Extraction Review Drawer/Modal state
  const [reviewDocId, setReviewDocId] = useState<string | null>(null)
  const [reviewFieldsData, setReviewFieldsData] = useState<ApiDocumentFieldsResponse | null>(null)
  const [isLoadingFields, setIsLoadingFields] = useState(false)
  const [isExtractingDocId, setIsExtractingDocId] = useState<string | null>(null)
  const [extractionActionError, setExtractionActionError] = useState<string | null>(null)
  const [extractionActionSuccess, setExtractionActionSuccess] = useState<string | null>(null)
  const [editingFieldId, setEditingFieldId] = useState<string | null>(null)
  const [editingFieldValue, setEditingFieldValue] = useState('')
  const [editingReason, setEditingReason] = useState('')
  const [isSavingField, setIsSavingField] = useState(false)
  const [isConfirmingFields, setIsConfirmingFields] = useState(false)

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
    } catch {
      // ignore
    }
  }

  const loadMetadata = async () => {
    try {
      const [projs, supps, lps] = await Promise.all([
        fetchProjects().catch(() => []),
        fetchSuppliers().catch(() => []),
        fetchLpos().catch(() => []),
      ])
      setProjectsList(projs)
      setSuppliersList(supps)
      setLposList(lps)
      if (projs.length > 0) setCreateProjectId((prev) => prev || projs[0].id || '')
      if (supps.length > 0) setCreateSupplierId((prev) => prev || supps[0].id || '')
    } catch {
      // ignore
    }
  }

  const handleOpenCreateModal = () => {
    setCreateCaseError(null)
    loadMetadata()
    setCreateWorkflow(openCreateWorkflow(createWorkflow))
  }

  const handleCreateCaseSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setCreateCaseError(null)

    const refErr = validateCaseRef(createCaseRef)
    if (refErr) {
      setCreateCaseError(refErr)
      return
    }
    if (!createProjectId) {
      setCreateCaseError('Please select a project.')
      return
    }
    if (!createSupplierId) {
      setCreateCaseError('Please select a supplier.')
      return
    }

    setIsSubmittingCase(true)
    try {
      const res = await createCase({
        case_ref: createCaseRef.trim(),
        project_id: createProjectId,
        supplier_id: createSupplierId,
        invoice_number_hint: createInvoiceHint.trim() || undefined,
        currency: 'AED',
        lpo_required: createLpoRequired,
        lpo_id: createLpoId || undefined,
      })

      await loadAllCases()
      setSelectedCaseId(res.case.id)
      setTab('Verify')
      setCreateWorkflow(closeCreateWorkflow(createWorkflow))
      setCreateCaseRef('')
      setCreateInvoiceHint('')
      setCreateLpoId('')
    } catch (err: any) {
      setCreateCaseError(err?.message || 'Failed to create case.')
    } finally {
      setIsSubmittingCase(false)
    }
  }

  const handleAddInvoiceLineSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedCase) return
    setInvLineError(null)

    if (!invDescription.trim()) {
      setInvLineError('Line description is required.')
      return
    }
    if (!validateDecimal(invQty, true)) {
      setInvLineError('Invoiced quantity must be a positive Decimal number (e.g. 36.00).')
      return
    }
    if (!validateDecimal(invUnitPrice, false) || !validateDecimal(invLineAmount, false)) {
      setInvLineError('Unit price and line amount must be non-negative Decimals.')
      return
    }

    setIsAddingInvLine(true)
    try {
      await addInvoiceLine(selectedCase.id, {
        line_no: Number(invLineNo),
        description: invDescription.trim(),
        invoiced_qty: invQty.trim(),
        unit: invUnit.trim(),
        unit_price: invUnitPrice.trim(),
        line_amount: invLineAmount.trim(),
      })
      await refreshCase(selectedCase.id)
      setInvLineNo((prev) => prev + 1)
      setInvDescription('')
      setInvQty('')
      setInvUnitPrice('')
      setInvLineAmount('')
    } catch (err: any) {
      setInvLineError(err?.message || 'Failed to add invoice line.')
    } finally {
      setIsAddingInvLine(false)
    }
  }

  const handleAddDnLineSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedCase) return
    setDnLineError(null)

    if (!dnNumber.trim()) {
      setDnLineError('Delivery note number is required.')
      return
    }
    if (!validateDecimal(dnDeliveredQty, true)) {
      setDnLineError('Delivered quantity must be a positive Decimal number.')
      return
    }
    if (dnRejectedQty && !validateDecimal(dnRejectedQty, false)) {
      setDnLineError('Rejected quantity must be a non-negative Decimal number.')
      return
    }

    setIsAddingDnLine(true)
    try {
      await addDnLine(selectedCase.id, {
        dn_number: dnNumber.trim(),
        line_no: Number(dnLineNo),
        description: dnDescription.trim() || `Material item ${dnLineNo}`,
        delivered_qty: dnDeliveredQty.trim(),
        unit: dnUnit.trim(),
        storekeeper_ticket_no: dnStoreTicket.trim() || undefined,
        storekeeper_confirmed: dnStoreConfirmed,
        rejected_qty: dnRejectedQty.trim() || undefined,
        rejection_reason_code: dnRejectionReason.trim() || undefined,
        has_rejection_evidence: dnHasRejectionEvidence,
      })
      await refreshCase(selectedCase.id)
      setDnLineNo((prev) => prev + 1)
      setDnDeliveredQty('')
      setDnRejectedQty('')
      setDnRejectionReason('')
      setDnHasRejectionEvidence(false)
    } catch (err: any) {
      setDnLineError(err?.message || 'Failed to add delivery note line.')
    } finally {
      setIsAddingDnLine(false)
    }
  }

  const handleCreateLinkSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedCase) return
    setLinkError(null)

    if (!linkInvLineId) {
      setLinkError('Please select an invoice line.')
      return
    }
    if (!linkDnLineId) {
      setLinkError('Please select a delivery note line.')
      return
    }

    setIsLinking(true)
    try {
      await createLineLink(selectedCase.id, {
        invoice_line_id: linkInvLineId,
        dn_line_id: linkDnLineId,
        lpo_line_id: linkLpoLineId || undefined,
      })
      await refreshCase(selectedCase.id)
      setLinkInvLineId('')
      setLinkDnLineId('')
      setLinkLpoLineId('')
    } catch (err: any) {
      setLinkError(err?.message || 'Failed to link lines.')
    } finally {
      setIsLinking(false)
    }
  }

  const handleRunVerification = async () => {
    if (!selectedCase) return
    setIsRunningVerification(true)
    setVerifyError(null)
    setVerifySuccess(null)
    try {
      const runRes = await runVerification(selectedCase.id)
      await refreshCase(selectedCase.id)
      setVerifySuccess(
        `Automated verification run #${runRes.run.run_no} executed successfully. Summary: ${runRes.run.summary || 'Checks completed.'}`
      )
    } catch (err: any) {
      setVerifyError(err?.message || 'Verification execution failed.')
    } finally {
      setIsRunningVerification(false)
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

  const isSodViolation = Boolean(
    currentUser &&
    selectedCase &&
    selectedCase.createdBy &&
    currentUser.id === selectedCase.createdBy
  )
  const canUserReview = Boolean(currentUser?.can_review)
  const isReviewAllowed = isReviewSubmittable && canUserReview && !isSodViolation

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

  const handleTriggerExtract = async (docId: string) => {
    setIsExtractingDocId(docId)
    setExtractionActionError(null)
    setExtractionActionSuccess(null)
    try {
      await triggerExtraction(docId)
      setExtractionActionSuccess('AI extraction completed. Values marked untrusted awaiting human confirmation.')
      if (selectedCase) {
        await refreshCase(selectedCase.id)
      }
      // Also open review drawer for this document
      handleOpenFieldReview(docId)
    } catch (err) {
      if (err instanceof ApiError) {
        setExtractionActionError(`Extraction error [${err.code}]: ${err.message}`)
      } else {
        setExtractionActionError(`Extraction failed: ${String(err)}`)
      }
    } finally {
      setIsExtractingDocId(null)
    }
  }

  const handleOpenFieldReview = async (docId: string) => {
    setReviewDocId(docId)
    setIsLoadingFields(true)
    setExtractionActionError(null)
    setExtractionActionSuccess(null)
    setEditingFieldId(null)
    try {
      const data = await fetchDocumentFields(docId)
      setReviewFieldsData(data)
    } catch (err) {
      setExtractionActionError(`Failed to load fields: ${String(err)}`)
    } finally {
      setIsLoadingFields(false)
    }
  }

  const handleSaveFieldCorrection = async (fieldId: string) => {
    if (!reviewDocId) return
    setIsSavingField(true)
    setExtractionActionError(null)
    try {
      await updateExtractedField(reviewDocId, fieldId, editingFieldValue, editingReason)
      setEditingFieldId(null)
      setEditingFieldValue('')
      setEditingReason('')
      setExtractionActionSuccess('Field correction saved with immutable audit revision.')
      // Refresh fields
      const refreshed = await fetchDocumentFields(reviewDocId)
      setReviewFieldsData(refreshed)
      if (selectedCase) {
        await refreshCase(selectedCase.id)
      }
    } catch (err) {
      setExtractionActionError(`Failed to update field: ${String(err)}`)
    } finally {
      setIsSavingField(false)
    }
  }

  const handleConfirmFields = async (docId: string) => {
    setIsConfirmingFields(true)
    setExtractionActionError(null)
    try {
      const res = await confirmDocumentFields(docId)
      setExtractionActionSuccess(`All fields confirmed (${res.confirmed_count} promoted to CONFIRMED). Trust established for verification.`)
      const refreshed = await fetchDocumentFields(docId)
      setReviewFieldsData(refreshed)
      if (selectedCase) {
        await refreshCase(selectedCase.id)
      }
    } catch (err) {
      setExtractionActionError(`Failed to confirm fields: ${String(err)}`)
    } finally {
      setIsConfirmingFields(false)
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

  const renderStatus = (status: string, hidePrefix = false) => {
    switch (status) {
      case 'Matched':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-emerald-50 text-emerald-700 border border-emerald-200">
            <CheckCircle2 className="w-3 h-3 text-emerald-600" />
            {!hidePrefix && <span className="text-[10px] uppercase font-bold opacity-75 mr-0.5">Engine:</span>}
            Matched
          </span>
        )
      case 'Mismatch':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-rose-50 text-rose-700 border border-rose-200">
            <XCircle className="w-3 h-3 text-rose-600" />
            {!hidePrefix && <span className="text-[10px] uppercase font-bold opacity-75 mr-0.5">Engine:</span>}
            Mismatch
          </span>
        )
      case 'Missing':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-amber-50 text-amber-700 border border-amber-200">
            <AlertTriangle className="w-3 h-3 text-amber-600" />
            {!hidePrefix && <span className="text-[10px] uppercase font-bold opacity-75 mr-0.5">Engine:</span>}
            Missing
          </span>
        )
      case 'Uncertain':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-slate-100 text-slate-700 border border-slate-300">
            <HelpCircle className="w-3 h-3 text-slate-500" />
            {!hidePrefix && <span className="text-[10px] uppercase font-bold opacity-75 mr-0.5">Engine:</span>}
            Uncertain
          </span>
        )
      default:
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-blue-50 text-blue-700 border border-blue-200">
            {!hidePrefix && <span className="text-[10px] uppercase font-bold opacity-75 mr-0.5">Engine:</span>}
            {status || 'Pending'}
          </span>
        )
    }
  }

  const renderReviewStatus = (outcome?: string) => {
    if (!outcome) return null
    let colorClasses = 'bg-slate-100 text-slate-700 border-slate-200'
    let icon = null
    if (outcome.includes('Verified')) {
      colorClasses = outcome.includes('Clean')
        ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
        : 'bg-teal-50 text-teal-700 border-teal-200'
      icon = <CheckCircle2 className="w-2.5 h-2.5 text-teal-600" />
    } else if (outcome.includes('On Hold')) {
      colorClasses = 'bg-amber-50 text-amber-700 border-amber-200'
      icon = <AlertTriangle className="w-2.5 h-2.5 text-amber-600" />
    } else if (outcome.includes('Rejected')) {
      colorClasses = 'bg-rose-50 text-rose-700 border-rose-200'
      icon = <XCircle className="w-2.5 h-2.5 text-rose-600" />
    }

    return (
      <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium border whitespace-nowrap ${colorClasses}`}>
        {icon}
        <span className="text-[9px] uppercase font-bold opacity-75 mr-0.5 shrink-0">Sign-off:</span>
        <span className="truncate">{outcome}</span>
      </span>
    )
  }

  const renderRuleNotes = (inv: ExtendedInvoiceRecord) => {
    const isPending =
      inv.verificationStatus === 'Pending' ||
      inv.verificationStatus === 'Ready to Verify' ||
      (!inv.verificationStatus && inv.status === 'Pending')

    if (isPending) {
      return <span className="text-slate-400 font-medium">Pending verification</span>
    }
    if (inv.hasQuantityMismatch) {
      return <span className="text-rose-600 font-medium">Quantity mismatch (D1)</span>
    }
    if (inv.hasMissingEvidence) {
      return <span className="text-amber-600 font-medium">Missing evidence (F8)</span>
    }
    if (inv.hasDnReuse) {
      return <span className="text-blue-600 font-medium">DN reuse flagged (C1)</span>
    }
    return <span className="text-emerald-600 font-medium">Exact match</span>
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
                onClick={handleOpenCreateModal}
                className="bg-slate-900 hover:bg-slate-800 text-white text-xs font-semibold px-3 py-1.5 rounded-md flex items-center gap-1.5 transition-colors border border-slate-900 shadow-2xs cursor-pointer"
                title="Create a new verification case (QS/Admin only)"
              >
                <Plus className="w-3.5 h-3.5 text-teal-400" />
                <span>Create Case</span>
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
                      <span className="text-[10px] bg-slate-100 text-slate-700 px-2 py-0.5 rounded font-medium border border-slate-200">
                        Active Cases Register
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
                              <td className="py-3 px-4 font-mono text-slate-600">
                                <div className="font-semibold text-slate-800">{inv.case_ref || inv.invoiceNo}</div>
                                {inv.case_ref && inv.case_ref !== inv.invoiceNo && (
                                  <div className="text-[10px] text-slate-400 font-mono">Inv: {inv.invoiceNo}</div>
                                )}
                              </td>
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
                                {renderRuleNotes(inv)}
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
                  <div className="flex items-center gap-3 text-xs">
                    <span className="text-slate-400">Filter:</span>
                    <span className="font-semibold text-slate-700">All Cases</span>
                    <button
                      onClick={handleOpenCreateModal}
                      className="bg-teal-700 hover:bg-teal-800 text-white font-semibold px-2.5 py-1 rounded text-xs flex items-center gap-1 transition-colors cursor-pointer"
                    >
                      <Plus className="w-3.5 h-3.5" />
                      <span>New Case</span>
                    </button>
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
                            <td className="py-3 px-4 font-mono">
                              <div className="font-semibold text-slate-800">{inv.case_ref || inv.invoiceNo}</div>
                              {inv.case_ref && inv.case_ref !== inv.invoiceNo && (
                                <div className="text-[10px] text-slate-400 font-mono">Inv: {inv.invoiceNo}</div>
                              )}
                            </td>
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
                              {renderRuleNotes(inv)}
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
                          {inv.case_ref || inv.invoiceNo} — {inv.supplier} ({inv.invoiceNo}) [{inv.status}]
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
                      <span className="text-slate-400 block text-[10px] uppercase">Case Reference</span>
                      <span className="font-bold text-slate-900 font-mono">{selectedCase.case_ref || selectedCase.invoiceNo}</span>
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
                      Encrypted Document Vault • Audit Indexed
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
                              className="flex flex-col sm:flex-row sm:items-center justify-between p-2.5 bg-slate-50 rounded border border-slate-200 text-xs gap-2"
                            >
                              <div className="flex items-center gap-2 truncate">
                                <FileText className="w-3.5 h-3.5 text-slate-600 shrink-0" />
                                <span className="font-mono text-slate-800 truncate">
                                  {doc.original_filename}
                                </span>
                                {doc.extraction_status === 'EXTRACTED' ? (
                                  <span className={`text-[10px] px-1.5 py-0.5 rounded border font-mono ${
                                    doc.data_review_status === 'CONFIRMED'
                                      ? 'bg-emerald-50 text-emerald-700 border-emerald-300'
                                      : 'bg-amber-50 text-amber-700 border-amber-300'
                                  }`}>
                                    {doc.data_review_status === 'CONFIRMED' ? 'AI CONFIRMED' : 'AI UNREVIEWED'}
                                  </span>
                                ) : null}
                              </div>
                              <div className="flex items-center gap-2 shrink-0">
                                <button
                                  type="button"
                                  onClick={() => handleTriggerExtract(doc.id)}
                                  disabled={isExtractingDocId === doc.id}
                                  className="inline-flex items-center gap-1 text-[11px] bg-teal-50 hover:bg-teal-100 text-teal-800 border border-teal-200 px-2 py-0.5 rounded font-medium cursor-pointer disabled:opacity-50"
                                >
                                  <Sparkles className="w-3 h-3 text-teal-600" />
                                  <span>{isExtractingDocId === doc.id ? 'Extracting...' : 'AI Extract'}</span>
                                </button>
                                <button
                                  type="button"
                                  onClick={() => handleOpenFieldReview(doc.id)}
                                  className="inline-flex items-center gap-1 text-[11px] text-slate-700 hover:text-slate-900 font-medium px-1.5 py-0.5 rounded border border-slate-200 bg-white cursor-pointer"
                                >
                                  <span>Review Fields</span>
                                </button>
                                <a
                                  href={getDocumentContentUrl(doc.id)}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="inline-flex items-center gap-1 text-[11px] text-slate-500 hover:text-slate-700 font-medium ml-1"
                                >
                                  <ExternalLink className="w-3 h-3" />
                                  <span>Preview</span>
                                </a>
                              </div>
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
                              className="flex flex-col sm:flex-row sm:items-center justify-between p-2.5 bg-slate-50 rounded border border-slate-200 text-xs gap-2"
                            >
                              <div className="flex items-center gap-2 truncate">
                                <FileCheck2 className="w-3.5 h-3.5 text-teal-600 shrink-0" />
                                <span className="font-mono text-slate-800 truncate">
                                  {doc.original_filename}
                                </span>
                                {doc.extraction_status === 'EXTRACTED' ? (
                                  <span className={`text-[10px] px-1.5 py-0.5 rounded border font-mono ${
                                    doc.data_review_status === 'CONFIRMED'
                                      ? 'bg-emerald-50 text-emerald-700 border-emerald-300'
                                      : 'bg-amber-50 text-amber-700 border-amber-300'
                                  }`}>
                                    {doc.data_review_status === 'CONFIRMED' ? 'AI CONFIRMED' : 'AI UNREVIEWED'}
                                  </span>
                                ) : null}
                              </div>
                              <div className="flex items-center gap-2 shrink-0">
                                <button
                                  type="button"
                                  onClick={() => handleTriggerExtract(doc.id)}
                                  disabled={isExtractingDocId === doc.id}
                                  className="inline-flex items-center gap-1 text-[11px] bg-teal-50 hover:bg-teal-100 text-teal-800 border border-teal-200 px-2 py-0.5 rounded font-medium cursor-pointer disabled:opacity-50"
                                >
                                  <Sparkles className="w-3 h-3 text-teal-600" />
                                  <span>{isExtractingDocId === doc.id ? 'Extracting...' : 'AI Extract'}</span>
                                </button>
                                <button
                                  type="button"
                                  onClick={() => handleOpenFieldReview(doc.id)}
                                  className="inline-flex items-center gap-1 text-[11px] text-slate-700 hover:text-slate-900 font-medium px-1.5 py-0.5 rounded border border-slate-200 bg-white cursor-pointer"
                                >
                                  <span>Review Fields</span>
                                </button>
                                <a
                                  href={getDocumentContentUrl(doc.id)}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="inline-flex items-center gap-1 text-[11px] text-slate-500 hover:text-slate-700 font-medium ml-1"
                                >
                                  <ExternalLink className="w-3 h-3" />
                                  <span>Preview</span>
                                </a>
                              </div>
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

                  {selectedCase.lines.length === 1 && selectedCase.lines[0].item === 'Material Item Verification' && selectedCase.lines[0].invQty === '—' && (
                    <div className="p-4 bg-slate-50/70 border-b border-slate-200 text-center text-xs text-slate-500">
                      <div className="flex items-center justify-center gap-1.5 font-semibold text-slate-700 mb-1">
                        <Layers className="w-4 h-4 text-teal-600" />
                        <span>No verification results recorded yet</span>
                      </div>
                      <p className="text-[11px] text-slate-500 max-w-md mx-auto">
                        Enter invoice lines and delivery tickets in the workspace below, link matching evidence, then run automated verification to evaluate discrepancies.
                      </p>
                    </div>
                  )}

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
                            <td className="py-3 px-4">{renderStatus(row.status, true)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Manual Evidence Entry & Line Linking (M4C Step 4) */}
                <div className="bg-white border border-slate-200 rounded-lg shadow-2xs overflow-hidden space-y-4 p-5">
                  <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-3">
                    <div className="flex items-center gap-2">
                      <Layers className="w-4 h-4 text-teal-600" />
                      <h4 className="text-xs font-bold text-slate-900 uppercase tracking-wider">
                        Reconciliation Data Entry & Multi-Way Linking
                      </h4>
                      <span className="text-[10px] bg-teal-50 text-teal-700 border border-teal-200 px-1.5 py-0.5 rounded font-mono">
                        QS Workspace
                      </span>
                    </div>

                    <button
                      onClick={handleRunVerification}
                      disabled={isRunningVerification}
                      className="bg-slate-900 hover:bg-slate-800 text-white text-xs font-semibold px-3 py-1.5 rounded-md flex items-center gap-1.5 shadow-2xs transition-colors cursor-pointer disabled:bg-slate-300"
                    >
                      <Sparkles className="w-3.5 h-3.5 text-teal-400" />
                      <span>{isRunningVerification ? 'Running Engine...' : 'Run Automated Verification'}</span>
                    </button>
                  </div>

                  {/* 4-Step Verification Workflow Indicator */}
                  <div className="bg-slate-50 border border-slate-200 rounded-lg p-3">
                    <div className="flex items-center justify-between text-[11px] font-bold text-slate-500 uppercase tracking-wider mb-2">
                      <span>4-Step Verification Workflow</span>
                      <span className="font-normal normal-case text-slate-400">Step-by-step audit progression</span>
                    </div>
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                      <button
                        type="button"
                        onClick={() => setDataEntryTab('invoice')}
                        className={`p-2.5 rounded border text-left transition-colors cursor-pointer ${
                          dataEntryTab === 'invoice'
                            ? 'border-teal-500 bg-teal-50/50 ring-1 ring-teal-500/30'
                            : (selectedCase.lineItems?.filter((l) => l.doc_type === 'INVOICE').length || 0) > 0
                            ? 'border-slate-200 bg-white hover:bg-slate-100/50'
                            : 'border-slate-200 bg-white hover:bg-slate-100/50'
                        }`}
                      >
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-[10px] font-bold text-slate-400 uppercase">Step 1</span>
                          {(selectedCase.lineItems?.filter((l) => l.doc_type === 'INVOICE').length || 0) > 0 ? (
                            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
                          ) : (
                            <span className="w-2 h-2 rounded-full bg-amber-400" />
                          )}
                        </div>
                        <div className="font-semibold text-xs text-slate-900">Invoice Lines</div>
                        <div className="text-[10px] text-slate-500 font-mono mt-0.5">
                          {(selectedCase.lineItems?.filter((l) => l.doc_type === 'INVOICE').length || 0) > 0
                            ? `${selectedCase.lineItems?.filter((l) => l.doc_type === 'INVOICE').length} line(s) added`
                            : 'Awaiting input'}
                        </div>
                      </button>

                      <button
                        type="button"
                        onClick={() => setDataEntryTab('dn')}
                        className={`p-2.5 rounded border text-left transition-colors cursor-pointer ${
                          dataEntryTab === 'dn'
                            ? 'border-teal-500 bg-teal-50/50 ring-1 ring-teal-500/30'
                            : (selectedCase.lineItems?.filter((l) => l.doc_type === 'DELIVERY_NOTE').length || 0) > 0
                            ? 'border-slate-200 bg-white hover:bg-slate-100/50'
                            : 'border-slate-200 bg-white hover:bg-slate-100/50'
                        }`}
                      >
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-[10px] font-bold text-slate-400 uppercase">Step 2</span>
                          {(selectedCase.lineItems?.filter((l) => l.doc_type === 'DELIVERY_NOTE').length || 0) > 0 ? (
                            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
                          ) : (
                            <span className="w-2 h-2 rounded-full bg-slate-300" />
                          )}
                        </div>
                        <div className="font-semibold text-xs text-slate-900">Delivery Notes</div>
                        <div className="text-[10px] text-slate-500 font-mono mt-0.5">
                          {(selectedCase.lineItems?.filter((l) => l.doc_type === 'DELIVERY_NOTE').length || 0) > 0
                            ? `${selectedCase.lineItems?.filter((l) => l.doc_type === 'DELIVERY_NOTE').length} ticket(s) added`
                            : 'Awaiting input'}
                        </div>
                      </button>

                      <button
                        type="button"
                        onClick={() => setDataEntryTab('links')}
                        className={`p-2.5 rounded border text-left transition-colors cursor-pointer ${
                          dataEntryTab === 'links'
                            ? 'border-teal-500 bg-teal-50/50 ring-1 ring-teal-500/30'
                            : (selectedCase.lineLinks?.length || 0) > 0
                            ? 'border-slate-200 bg-white hover:bg-slate-100/50'
                            : 'border-slate-200 bg-white hover:bg-slate-100/50'
                        }`}
                      >
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-[10px] font-bold text-slate-400 uppercase">Step 3</span>
                          {(selectedCase.lineLinks?.length || 0) > 0 ? (
                            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
                          ) : (
                            <span className="w-2 h-2 rounded-full bg-slate-300" />
                          )}
                        </div>
                        <div className="font-semibold text-xs text-slate-900">Link Evidence</div>
                        <div className="text-[10px] text-slate-500 font-mono mt-0.5">
                          {(selectedCase.lineLinks?.length || 0) > 0
                            ? `${selectedCase.lineLinks?.length} link(s) established`
                            : 'Awaiting links'}
                        </div>
                      </button>

                      <button
                        type="button"
                        onClick={handleRunVerification}
                        disabled={isRunningVerification}
                        className={`p-2.5 rounded border text-left transition-colors cursor-pointer ${
                          selectedCase.verificationStatus &&
                          selectedCase.verificationStatus !== 'Pending' &&
                          selectedCase.verificationStatus !== 'Ready to Verify'
                            ? 'border-emerald-300 bg-emerald-50/40 hover:bg-emerald-50/70'
                            : 'border-slate-900 bg-slate-900 text-white hover:bg-slate-800'
                        }`}
                      >
                        <div className="flex items-center justify-between mb-1">
                          <span
                            className={`text-[10px] font-bold uppercase ${
                              selectedCase.verificationStatus &&
                              selectedCase.verificationStatus !== 'Pending' &&
                              selectedCase.verificationStatus !== 'Ready to Verify'
                                ? 'text-emerald-700'
                                : 'text-teal-400'
                            }`}
                          >
                            Step 4
                          </span>
                          {selectedCase.verificationStatus &&
                          selectedCase.verificationStatus !== 'Pending' &&
                          selectedCase.verificationStatus !== 'Ready to Verify' ? (
                            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
                          ) : (
                            <Sparkles className="w-3.5 h-3.5 text-teal-400 animate-pulse" />
                          )}
                        </div>
                        <div
                          className={`font-semibold text-xs ${
                            selectedCase.verificationStatus &&
                            selectedCase.verificationStatus !== 'Pending' &&
                            selectedCase.verificationStatus !== 'Ready to Verify'
                              ? 'text-slate-900'
                              : 'text-white'
                          }`}
                        >
                          Run Verification
                        </div>
                        <div
                          className={`text-[10px] font-mono mt-0.5 ${
                            selectedCase.verificationStatus &&
                            selectedCase.verificationStatus !== 'Pending' &&
                            selectedCase.verificationStatus !== 'Ready to Verify'
                              ? 'text-emerald-700'
                              : 'text-slate-300'
                          }`}
                        >
                          {isRunningVerification
                            ? 'Running...'
                            : selectedCase.verificationStatus &&
                              selectedCase.verificationStatus !== 'Pending' &&
                              selectedCase.verificationStatus !== 'Ready to Verify'
                            ? 'Engine verified'
                            : 'Click to run'}
                        </div>
                      </button>
                    </div>
                  </div>

                  {verifyError && (
                    <div className="p-2.5 bg-rose-50 border border-rose-200 rounded text-rose-800 text-xs flex items-center justify-between shadow-2xs">
                      <div className="flex items-center gap-2">
                        <XCircle className="w-4 h-4 text-rose-600 shrink-0" />
                        <span>{verifyError}</span>
                      </div>
                      <button
                        onClick={() => setVerifyError(null)}
                        className="text-rose-600 hover:text-rose-900 cursor-pointer"
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  )}

                  {verifySuccess && (
                    <div className="p-2.5 bg-emerald-50 border border-emerald-200 rounded text-emerald-900 text-xs flex items-center justify-between shadow-2xs">
                      <div className="flex items-center gap-2">
                        <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
                        <span>{verifySuccess}</span>
                      </div>
                      <button
                        onClick={() => setVerifySuccess(null)}
                        className="text-emerald-600 hover:text-emerald-900 cursor-pointer"
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  )}

                  {/* Sub-Tabs: 1. Invoice Lines, 2. Delivery Note Lines, 3. Line Linking */}
                  <div className="flex items-center gap-2 border-b border-slate-200 pb-2 text-xs">
                    <button
                      onClick={() => setDataEntryTab('invoice')}
                      className={`px-3 py-1 rounded font-medium transition-colors cursor-pointer ${
                        dataEntryTab === 'invoice'
                          ? 'bg-slate-900 text-white font-semibold'
                          : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                      }`}
                    >
                      1. Invoiced Lines ({selectedCase.lineItems?.filter((l) => l.doc_type === 'INVOICE').length || 0})
                    </button>
                    <button
                      onClick={() => setDataEntryTab('dn')}
                      className={`px-3 py-1 rounded font-medium transition-colors cursor-pointer ${
                        dataEntryTab === 'dn'
                          ? 'bg-slate-900 text-white font-semibold'
                          : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                      }`}
                    >
                      2. Delivery Note Lines ({selectedCase.lineItems?.filter((l) => l.doc_type === 'DELIVERY_NOTE').length || 0})
                    </button>
                    <button
                      onClick={() => setDataEntryTab('links')}
                      className={`px-3 py-1 rounded font-medium transition-colors cursor-pointer ${
                        dataEntryTab === 'links'
                          ? 'bg-slate-900 text-white font-semibold'
                          : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                      }`}
                    >
                      3. Multi-Way Linking ({selectedCase.lineLinks?.length || 0})
                    </button>
                  </div>

                  {/* SUBTAB 1: INVOICE LINES */}
                  {dataEntryTab === 'invoice' && (
                    <div className="space-y-4">
                      {invLineError && (
                        <div className="p-2.5 bg-rose-50 border border-rose-200 rounded text-rose-800 text-xs flex items-center gap-2">
                          <XCircle className="w-4 h-4 text-rose-600 shrink-0" />
                          <span>{invLineError}</span>
                        </div>
                      )}

                      <form onSubmit={handleAddInvoiceLineSubmit} className="bg-slate-50 p-3.5 rounded-lg border border-slate-200 space-y-3">
                        <div className="text-[11px] font-semibold text-slate-700 uppercase tracking-wider">
                          Add Invoiced Line Item (Exact Decimal)
                        </div>
                        <div className="grid grid-cols-1 sm:grid-cols-6 gap-3 text-xs">
                          <div className="sm:col-span-1">
                            <label className="block text-slate-600 text-[11px] mb-1">Line #</label>
                            <input
                              type="number"
                              min={1}
                              value={invLineNo}
                              onChange={(e) => setInvLineNo(Number(e.target.value))}
                              className="w-full border border-slate-300 rounded px-2 py-1.5 bg-white text-slate-900 text-xs"
                              required
                            />
                          </div>
                          <div className="sm:col-span-2">
                            <label className="block text-slate-600 text-[11px] mb-1">Description</label>
                            <input
                              type="text"
                              placeholder="ReadyMix Concrete C40/20"
                              value={invDescription}
                              onChange={(e) => setInvDescription(e.target.value)}
                              className="w-full border border-slate-300 rounded px-2 py-1.5 bg-white text-slate-900 text-xs"
                              required
                            />
                          </div>
                          <div className="sm:col-span-1">
                            <label className="block text-slate-600 text-[11px] mb-1">Invoiced Qty</label>
                            <input
                              type="text"
                              placeholder="36.00"
                              value={invQty}
                              onChange={(e) => setInvQty(e.target.value)}
                              className="w-full border border-slate-300 rounded px-2 py-1.5 bg-white text-slate-900 text-xs font-mono"
                              required
                            />
                          </div>
                          <div className="sm:col-span-1">
                            <label className="block text-slate-600 text-[11px] mb-1">Unit</label>
                            <select
                              value={invUnit}
                              onChange={(e) => setInvUnit(e.target.value)}
                              className="w-full border border-slate-300 rounded px-2 py-1.5 bg-white text-slate-900 text-xs"
                            >
                              <option value="m3">m3</option>
                              <option value="t">t</option>
                              <option value="kg">kg</option>
                              <option value="pcs">pcs</option>
                            </select>
                          </div>
                          <div className="sm:col-span-1">
                            <label className="block text-slate-600 text-[11px] mb-1">Rate (AED)</label>
                            <input
                              type="text"
                              placeholder="240.00"
                              value={invUnitPrice}
                              onChange={(e) => {
                                const rate = e.target.value
                                setInvUnitPrice(rate)
                                if (invQty && !isNaN(Number(invQty)) && !isNaN(Number(rate))) {
                                  setInvLineAmount((Number(invQty) * Number(rate)).toFixed(2))
                                }
                              }}
                              className="w-full border border-slate-300 rounded px-2 py-1.5 bg-white text-slate-900 text-xs font-mono"
                              required
                            />
                          </div>
                        </div>

                        <div className="flex items-center justify-between pt-1">
                          <div className="text-xs text-slate-500 font-mono">
                            Line Total: <span className="font-semibold text-slate-900">AED {invLineAmount || '0.00'}</span>
                          </div>
                          <button
                            type="submit"
                            disabled={isAddingInvLine}
                            className="bg-teal-700 hover:bg-teal-800 text-white font-semibold text-xs px-3 py-1.5 rounded transition-colors cursor-pointer disabled:bg-slate-300"
                          >
                            {isAddingInvLine ? 'Adding Line...' : '+ Add Invoiced Line'}
                          </button>
                        </div>
                      </form>

                      {/* Existing Invoiced Lines List */}
                      <div className="border border-slate-200 rounded-lg overflow-hidden">
                        <div className="px-3 py-2 bg-slate-100/70 border-b border-slate-200 text-[11px] font-semibold text-slate-700 flex justify-between">
                          <span>Recorded Invoiced Lines</span>
                          <span className="font-mono text-slate-500">
                            {selectedCase.lineItems?.filter((l) => l.doc_type === 'INVOICE').length || 0} line(s)
                          </span>
                        </div>
                        <div className="divide-y divide-slate-100 text-xs">
                          {selectedCase.lineItems?.filter((l) => l.doc_type === 'INVOICE').length ? (
                            selectedCase.lineItems
                              .filter((l) => l.doc_type === 'INVOICE')
                              .map((li) => (
                                <div key={li.id} className="p-3 flex items-center justify-between hover:bg-slate-50/50">
                                  <div>
                                    <span className="font-semibold text-slate-900 font-mono mr-2">Line {li.line_no}:</span>
                                    <span className="text-slate-800">{li.fields?.description || `Invoice Line ${li.line_no}`}</span>
                                  </div>
                                  <div className="text-right font-mono">
                                    <span className="font-bold text-slate-900">{li.fields?.invoiced_qty || '—'} {li.fields?.unit || ''}</span>
                                    <span className="text-slate-500 text-[11px] block">
                                      @ AED {li.fields?.unit_price || '—'} = AED {li.fields?.line_amount || '—'}
                                    </span>
                                  </div>
                                </div>
                              ))
                          ) : (
                            <div className="p-4 text-center text-slate-400 text-xs">
                              No invoice lines recorded yet. Enter line details above to populate.
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  )}

                  {/* SUBTAB 2: DELIVERY NOTE LINES */}
                  {dataEntryTab === 'dn' && (
                    <div className="space-y-4">
                      {dnLineError && (
                        <div className="p-2.5 bg-rose-50 border border-rose-200 rounded text-rose-800 text-xs flex items-center gap-2">
                          <XCircle className="w-4 h-4 text-rose-600 shrink-0" />
                          <span>{dnLineError}</span>
                        </div>
                      )}

                      <form onSubmit={handleAddDnLineSubmit} className="bg-slate-50 p-3.5 rounded-lg border border-slate-200 space-y-3">
                        <div className="text-[11px] font-semibold text-slate-700 uppercase tracking-wider">
                          Log Delivery Note Ticket & Site Receipt
                        </div>
                        <div className="grid grid-cols-1 sm:grid-cols-6 gap-3 text-xs">
                          <div className="sm:col-span-2">
                            <label className="block text-slate-600 text-[11px] mb-1">DN Ticket #</label>
                            <input
                              type="text"
                              placeholder="DN-PILOT-301"
                              value={dnNumber}
                              onChange={(e) => setDnNumber(e.target.value)}
                              className="w-full border border-slate-300 rounded px-2 py-1.5 bg-white text-slate-900 text-xs font-mono"
                              required
                            />
                          </div>
                          <div className="sm:col-span-1">
                            <label className="block text-slate-600 text-[11px] mb-1">Line #</label>
                            <input
                              type="number"
                              min={1}
                              value={dnLineNo}
                              onChange={(e) => setDnLineNo(Number(e.target.value))}
                              className="w-full border border-slate-300 rounded px-2 py-1.5 bg-white text-slate-900 text-xs"
                              required
                            />
                          </div>
                          <div className="sm:col-span-2">
                            <label className="block text-slate-600 text-[11px] mb-1">Description</label>
                            <input
                              type="text"
                              placeholder="ReadyMix Concrete C40/20"
                              value={dnDescription}
                              onChange={(e) => setDnDescription(e.target.value)}
                              className="w-full border border-slate-300 rounded px-2 py-1.5 bg-white text-slate-900 text-xs"
                            />
                          </div>
                          <div className="sm:col-span-1">
                            <label className="block text-slate-600 text-[11px] mb-1">Delivered Qty</label>
                            <input
                              type="text"
                              placeholder="36.00"
                              value={dnDeliveredQty}
                              onChange={(e) => setDnDeliveredQty(e.target.value)}
                              className="w-full border border-slate-300 rounded px-2 py-1.5 bg-white text-slate-900 text-xs font-mono"
                              required
                            />
                          </div>
                          <div className="sm:col-span-1">
                            <label className="block text-slate-600 text-[11px] mb-1">Unit</label>
                            <select
                              value={dnUnit}
                              onChange={(e) => setDnUnit(e.target.value)}
                              className="w-full border border-slate-300 rounded px-2 py-1.5 bg-white text-slate-900 text-xs"
                            >
                              <option value="m3">m3</option>
                              <option value="t">t</option>
                              <option value="kg">kg</option>
                              <option value="pcs">pcs</option>
                            </select>
                          </div>
                        </div>

                        {/* Site Receipt & Rejection Section */}
                        <div className="border-t border-slate-200 pt-2.5 grid grid-cols-1 sm:grid-cols-4 gap-3 text-xs">
                          <div className="sm:col-span-2">
                            <label className="block text-slate-600 text-[11px] mb-1">Storekeeper Gate Ticket #</label>
                            <input
                              type="text"
                              placeholder="GATE-2026-0940"
                              value={dnStoreTicket}
                              onChange={(e) => setDnStoreTicket(e.target.value)}
                              className="w-full border border-slate-300 rounded px-2 py-1.5 bg-white text-slate-900 text-xs font-mono"
                            />
                          </div>
                          <div className="sm:col-span-1">
                            <label className="block text-slate-600 text-[11px] mb-1">Rejected Qty (if any)</label>
                            <input
                              type="text"
                              placeholder="0.00"
                              value={dnRejectedQty}
                              onChange={(e) => setDnRejectedQty(e.target.value)}
                              className="w-full border border-slate-300 rounded px-2 py-1.5 bg-white text-slate-900 text-xs font-mono"
                            />
                          </div>
                          <div className="sm:col-span-1">
                            <label className="block text-slate-600 text-[11px] mb-1">Rejection Reason</label>
                            <select
                              value={dnRejectionReason}
                              onChange={(e) => setDnRejectionReason(e.target.value)}
                              className="w-full border border-slate-300 rounded px-2 py-1.5 bg-white text-slate-900 text-xs"
                            >
                              <option value="">None (Accepted)</option>
                              <option value="SLUMP_FAILURE">Slump Failure</option>
                              <option value="DAMAGE_IN_TRANSIT">Transit Damage</option>
                              <option value="OFF_SPEC">Off Specification</option>
                            </select>
                          </div>
                        </div>

                        <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
                          <div className="flex items-center gap-4 text-xs text-slate-600">
                            <label className="flex items-center gap-1.5 cursor-pointer">
                              <input
                                type="checkbox"
                                checked={dnStoreConfirmed}
                                onChange={(e) => setDnStoreConfirmed(e.target.checked)}
                                className="rounded border-slate-300 text-teal-600"
                              />
                              <span>Storekeeper Gate Confirmed</span>
                            </label>
                            <label className="flex items-center gap-1.5 cursor-pointer">
                              <input
                                type="checkbox"
                                checked={dnHasRejectionEvidence}
                                onChange={(e) => setDnHasRejectionEvidence(e.target.checked)}
                                className="rounded border-slate-300 text-teal-600"
                              />
                              <span>Signed Rejection Remark on Ticket</span>
                            </label>
                          </div>
                          <button
                            type="submit"
                            disabled={isAddingDnLine}
                            className="bg-teal-700 hover:bg-teal-800 text-white font-semibold text-xs px-3 py-1.5 rounded transition-colors cursor-pointer disabled:bg-slate-300"
                          >
                            {isAddingDnLine ? 'Logging Ticket...' : '+ Log Delivery Ticket'}
                          </button>
                        </div>
                      </form>

                      {/* Recorded Delivery Notes List */}
                      <div className="border border-slate-200 rounded-lg overflow-hidden">
                        <div className="px-3 py-2 bg-slate-100/70 border-b border-slate-200 text-[11px] font-semibold text-slate-700 flex justify-between">
                          <span>Recorded Delivery Note Lines</span>
                          <span className="font-mono text-slate-500">
                            {selectedCase.lineItems?.filter((l) => l.doc_type === 'DELIVERY_NOTE').length || 0} line(s)
                          </span>
                        </div>
                        <div className="divide-y divide-slate-100 text-xs">
                          {selectedCase.lineItems?.filter((l) => l.doc_type === 'DELIVERY_NOTE').length ? (
                            selectedCase.lineItems
                              .filter((l) => l.doc_type === 'DELIVERY_NOTE')
                              .map((li) => (
                                <div key={li.id} className="p-3 flex items-center justify-between hover:bg-slate-50/50">
                                  <div>
                                    <span className="font-semibold text-slate-900 font-mono mr-2">
                                      {li.dn_number ? `DN ${li.dn_number}` : 'DN'} — Line {li.line_no}:
                                    </span>
                                    <span className="text-slate-800">{li.fields?.description || 'Delivered Material'}</span>
                                    <div className="text-[11px] text-slate-500 flex items-center gap-3 mt-1 font-mono">
                                      <span>Ticket: {li.storekeeper_ticket_no || 'None'}</span>
                                      {li.rejected_qty && (
                                        <span className="text-amber-700 bg-amber-50 px-1.5 py-0.5 rounded border border-amber-200">
                                          Rejected: {li.rejected_qty} {li.fields?.unit || ''} ({li.rejection_reason_code || 'Documented'})
                                        </span>
                                      )}
                                    </div>
                                  </div>
                                  <div className="text-right font-mono">
                                    <span className="font-bold text-slate-900 block">
                                      {li.fields?.delivered_qty || '—'} {li.fields?.unit || ''}
                                    </span>
                                    <span className="text-[10px] text-emerald-700 bg-emerald-50 px-1.5 py-0.5 rounded border border-emerald-200 inline-block mt-0.5">
                                      Gate Verified
                                    </span>
                                  </div>
                                </div>
                              ))
                          ) : (
                            <div className="p-4 text-center text-slate-400 text-xs">
                              No delivery note lines recorded yet. Log delivery note tickets above.
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  )}

                  {/* SUBTAB 3: MULTI-WAY LINE LINKING */}
                  {dataEntryTab === 'links' && (
                    <div className="space-y-4">
                      {linkError && (
                        <div className="p-2.5 bg-rose-50 border border-rose-200 rounded text-rose-800 text-xs flex items-center gap-2">
                          <XCircle className="w-4 h-4 text-rose-600 shrink-0" />
                          <span>{linkError}</span>
                        </div>
                      )}

                      <form onSubmit={handleCreateLinkSubmit} className="bg-slate-50 p-3.5 rounded-lg border border-slate-200 space-y-3">
                        <div className="text-[11px] font-semibold text-slate-700 uppercase tracking-wider flex items-center justify-between">
                          <span>Associate Invoice Line to Delivery Ticket (Rule P2)</span>
                          <span className="text-[10px] text-slate-400 font-mono">1 DN Line ↔ 1 Invoice Line</span>
                        </div>

                        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
                          <div>
                            <label className="block text-slate-600 text-[11px] mb-1">Invoice Line</label>
                            <select
                              value={linkInvLineId}
                              onChange={(e) => setLinkInvLineId(e.target.value)}
                              className="w-full border border-slate-300 rounded px-2.5 py-1.5 bg-white text-slate-900 text-xs"
                              required
                            >
                              <option value="">Select Invoice Line...</option>
                              {selectedCase.lineItems
                                ?.filter((l) => l.doc_type === 'INVOICE')
                                .map((l) => (
                                  <option key={l.id} value={l.id}>
                                    Line {l.line_no}: {l.fields?.invoiced_qty || '0'} {l.fields?.unit || ''} (@ AED {l.fields?.unit_price || '—'})
                                  </option>
                                ))}
                            </select>
                          </div>

                          <div>
                            <label className="block text-slate-600 text-[11px] mb-1">Delivery Note Line</label>
                            <select
                              value={linkDnLineId}
                              onChange={(e) => setLinkDnLineId(e.target.value)}
                              className="w-full border border-slate-300 rounded px-2.5 py-1.5 bg-white text-slate-900 text-xs"
                              required
                            >
                              <option value="">Select Delivery Note Line...</option>
                              {selectedCase.lineItems
                                ?.filter((l) => l.doc_type === 'DELIVERY_NOTE')
                                .map((l) => {
                                  const isAlreadyLinked = selectedCase.lineLinks?.some((link) => link.dn_line_id === l.id)
                                  return (
                                    <option key={l.id} value={l.id} disabled={isAlreadyLinked}>
                                      {l.dn_number || 'DN'} (Line {l.line_no}): {l.fields?.delivered_qty || '0'} {l.fields?.unit || ''} {isAlreadyLinked ? '— [Already Linked (P2)]' : ''}
                                    </option>
                                  )
                                })}
                            </select>
                          </div>

                          <div>
                            <label className="block text-slate-600 text-[11px] mb-1">Contractual LPO Line (Optional)</label>
                            <select
                              value={linkLpoLineId}
                              onChange={(e) => setLinkLpoLineId(e.target.value)}
                              className="w-full border border-slate-300 rounded px-2.5 py-1.5 bg-white text-slate-900 text-xs"
                            >
                              <option value="">None / 2-Way Match</option>
                              {selectedCase.lpoRef && selectedCase.lpoRef !== 'Missing (Required)' ? (
                                <option value="lpo-line-pilot-rmc-01">LPO Line 1 (Contract Cap Match)</option>
                              ) : null}
                            </select>
                          </div>
                        </div>

                        <div className="flex items-center justify-end pt-1">
                          <button
                            type="submit"
                            disabled={isLinking}
                            className="bg-slate-900 hover:bg-slate-800 text-white font-semibold text-xs px-3.5 py-1.5 rounded transition-colors cursor-pointer flex items-center gap-1.5 disabled:bg-slate-300"
                          >
                            <Link2 className="w-3.5 h-3.5 text-teal-400" />
                            <span>{isLinking ? 'Linking...' : 'Confirm Reconciliation Link'}</span>
                          </button>
                        </div>
                      </form>

                      {/* Established Links Table */}
                      <div className="border border-slate-200 rounded-lg overflow-hidden">
                        <div className="px-3 py-2 bg-slate-100/70 border-b border-slate-200 text-[11px] font-semibold text-slate-700 flex justify-between">
                          <span>Established Reconciliation Links</span>
                          <span className="font-mono text-slate-500">
                            {selectedCase.lineLinks?.length || 0} active link(s)
                          </span>
                        </div>
                        <div className="divide-y divide-slate-100 text-xs">
                          {selectedCase.lineLinks && selectedCase.lineLinks.length > 0 ? (
                            selectedCase.lineLinks.map((link) => {
                              const invLine = selectedCase.lineItems?.find((li) => li.id === link.invoice_line_id)
                              const dnLine = selectedCase.lineItems?.find((li) => li.id === link.dn_line_id)
                              return (
                                <div key={link.id} className="p-3 flex items-center justify-between hover:bg-slate-50/50">
                                  <div className="flex items-center gap-3">
                                    <div className="p-1.5 bg-teal-50 border border-teal-200 rounded text-teal-700">
                                      <Link2 className="w-3.5 h-3.5" />
                                    </div>
                                    <div>
                                      <div className="font-semibold text-slate-900">
                                        Invoice Line {invLine?.line_no || '—'} ↔ {dnLine?.dn_number || 'DN'} (Line {dnLine?.line_no || '—'})
                                      </div>
                                      <div className="text-[11px] text-slate-400 font-mono mt-0.5">
                                        Inv: {invLine?.fields?.invoiced_qty || '—'} {invLine?.fields?.unit || ''} | Delivered: {dnLine?.fields?.delivered_qty || '—'} {dnLine?.fields?.unit || ''}
                                      </div>
                                    </div>
                                  </div>
                                  <div className="text-right">
                                    <span className="text-[10px] bg-emerald-100 text-emerald-800 font-mono font-medium px-2 py-0.5 rounded">
                                      {link.status}
                                    </span>
                                  </div>
                                </div>
                              )
                            })
                          ) : (
                            <div className="p-4 text-center text-slate-400 text-xs">
                              No reconciliation links established yet. Select invoice and delivery lines above to link them.
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  )}
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
                      Case {selectedCase.case_ref || selectedCase.invoiceNo} • {selectedCase.supplier} • {selectedCase.invoiceNo}
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

                  {/* SoD & Role Authorization Warnings */}
                  {isSodViolation && (
                    <div className="p-3.5 bg-amber-50 border border-amber-300 rounded-lg text-amber-900 text-xs flex items-start gap-2.5">
                      <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
                      <div>
                        <span className="font-bold block">Segregation of Duties (SoD) Active</span>
                        <p className="text-[11px] mt-0.5 leading-relaxed">
                          You created this verification case as <strong>{currentUser?.name}</strong> ({currentUser?.role}).
                          Under the four-eyes governance principle, case creators cannot record formal review sign-offs.
                          Please sign in as an independent Commercial Reviewer to review this case.
                        </p>
                      </div>
                    </div>
                  )}

                  {!canUserReview && !isSodViolation && (
                    <div className="p-3 bg-slate-100 border border-slate-300 rounded-md text-slate-700 text-xs flex items-start gap-2.5">
                      <Lock className="w-4 h-4 text-slate-500 shrink-0 mt-0.5" />
                      <div>
                        <span className="font-semibold block">Review Authorization Required (D6)</span>
                        <p className="text-[11px] mt-0.5 leading-relaxed">
                          Your active role (<strong>{currentUser?.role || 'Guest'}</strong>) does not have formal review sign-off permissions (can_review=False).
                        </p>
                      </div>
                    </div>
                  )}

                  {canUserReview && !isSodViolation && (selectedCase?.verificationStatus === 'Pending' || selectedCase?.status === 'Pending') && (
                    <div className="p-3.5 bg-blue-50 border border-blue-200 rounded-lg text-blue-900 text-xs flex items-start gap-2.5">
                      <Info className="w-4 h-4 text-blue-600 shrink-0 mt-0.5" />
                      <div>
                        <span className="font-bold block">Automated Verification Pending</span>
                        <p className="text-[11px] mt-0.5 leading-relaxed">
                          Automated discrepancy checks must be executed before a formal review decision can be recorded. Please run verification in the <strong>Verify</strong> tab first.
                        </p>
                      </div>
                    </div>
                  )}

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
                      disabled={!isReviewAllowed || isSubmittingReview}
                      className={`px-4 py-2 text-xs font-semibold rounded-md shadow-xs transition-colors ${
                        !isReviewAllowed || isSubmittingReview
                          ? 'bg-slate-200 text-slate-400 cursor-not-allowed'
                          : 'bg-slate-900 hover:bg-slate-800 text-white cursor-pointer'
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
              <div className="space-y-4 max-w-3xl mx-auto">
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
                          {inv.case_ref || inv.invoiceNo} — {inv.supplier} ({inv.invoiceNo}) [{inv.status}]
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="text-xs text-slate-400">
                    Audit trail recorded in PostgreSQL
                  </div>
                </div>

                <div className="bg-white border border-slate-200 rounded-lg p-6 shadow-2xs space-y-4">
                  <div className="border-b border-slate-100 pb-3 flex items-center justify-between">
                    <div>
                      <span className="text-xs font-bold text-slate-900 uppercase tracking-wider">
                        Case Audit History
                      </span>
                      <p className="text-[11px] text-slate-500 mt-0.5">
                        Case: <span className="font-mono font-semibold">{selectedCase.case_ref || selectedCase.invoiceNo}</span> • {selectedCase.supplier}
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
                      </div>
                    </div>
                  ))}
                </div>
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

      {/* Create Case Workflow Modal (M4C Step 4) */}
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
                  <span className="bg-teal-500/20 text-teal-300 text-[10px] font-mono px-2 py-0.5 rounded border border-teal-500/30">
                    New Case Setup
                  </span>
                </div>
                <p className="text-xs text-slate-400 mt-0.5">
                  Manual Ingestion & Multi-Way Verification Shell
                </p>
              </div>
              <button
                onClick={() => setCreateWorkflow(closeCreateWorkflow(createWorkflow))}
                className="text-slate-400 hover:text-white transition-colors cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Modal Body */}
            {!canCreateCase(currentUser?.role) ? (
              <div className="p-6 space-y-4 text-xs text-slate-600">
                <div className="p-3 bg-amber-50 border border-amber-200 rounded-lg text-amber-900 space-y-1">
                  <div className="flex items-center gap-1.5 font-bold">
                    <Lock className="w-4 h-4 text-amber-600 shrink-0" />
                    <span>Authorization Required (Role Protection)</span>
                  </div>
                  <p className="text-[11px] leading-relaxed">
                    Only authorized Quantity Surveyors (role: QS) and Administrators (role: ADMIN) may create new verification cases.
                    Your active role is <strong>{currentUser ? currentUser.role : 'Guest / Unauthenticated'}</strong>.
                  </p>
                </div>
                <p className="text-[11px] text-slate-500">
                  Please sign in as Ramesh QS (Project QS) or Khalfan Director (Commercial Director) to initiate cases.
                </p>
                <div className="flex justify-end pt-2">
                  <button
                    onClick={() => setCreateWorkflow(closeCreateWorkflow(createWorkflow))}
                    className="px-4 py-1.5 text-xs font-semibold bg-slate-900 hover:bg-slate-800 text-white rounded transition-colors cursor-pointer"
                  >
                    Close
                  </button>
                </div>
              </div>
            ) : (
              <form onSubmit={handleCreateCaseSubmit} className="p-6 space-y-4 text-xs text-slate-700">
                {createCaseError && (
                  <div className="p-2.5 bg-rose-50 border border-rose-200 rounded text-rose-800 text-xs flex items-center gap-2">
                    <XCircle className="w-4 h-4 text-rose-600 shrink-0" />
                    <span>{createCaseError}</span>
                  </div>
                )}

                <div className="space-y-3">
                  <div>
                    <label className="block font-semibold text-slate-800 mb-1">
                      Case Reference <span className="text-rose-500">*</span>
                    </label>
                    <input
                      type="text"
                      placeholder="e.g. CASE-2026-SYN-06"
                      value={createCaseRef}
                      onChange={(e) => setCreateCaseRef(e.target.value)}
                      className="w-full border border-slate-300 rounded px-2.5 py-1.5 bg-white text-slate-900 text-xs font-mono"
                      required
                    />
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div>
                      <label className="block font-semibold text-slate-800 mb-1">
                        Project Site <span className="text-rose-500">*</span>
                      </label>
                      <select
                        value={createProjectId}
                        onChange={(e) => setCreateProjectId(e.target.value)}
                        className="w-full border border-slate-300 rounded px-2.5 py-1.5 bg-white text-slate-900 text-xs"
                        required
                      >
                        {projectsList.map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.code} — {p.name}
                          </option>
                        ))}
                      </select>
                    </div>

                    <div>
                      <label className="block font-semibold text-slate-800 mb-1">
                        Supplier <span className="text-rose-500">*</span>
                      </label>
                      <select
                        value={createSupplierId}
                        onChange={(e) => setCreateSupplierId(e.target.value)}
                        className="w-full border border-slate-300 rounded px-2.5 py-1.5 bg-white text-slate-900 text-xs"
                        required
                      >
                        {suppliersList.map((s) => (
                          <option key={s.id} value={s.id}>
                            {s.name} (TRN: {s.trn})
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div>
                      <label className="block font-semibold text-slate-800 mb-1">
                        Invoice Reference Hint
                      </label>
                      <input
                        type="text"
                        placeholder="e.g. INV-SYN-2026-06"
                        value={createInvoiceHint}
                        onChange={(e) => setCreateInvoiceHint(e.target.value)}
                        className="w-full border border-slate-300 rounded px-2.5 py-1.5 bg-white text-slate-900 text-xs font-mono"
                      />
                    </div>

                    <div>
                      <label className="block font-semibold text-slate-800 mb-1">Currency</label>
                      <input
                        type="text"
                        value="AED (Fixed UAE Dirham)"
                        disabled
                        className="w-full border border-slate-200 rounded px-2.5 py-1.5 bg-slate-100 text-slate-500 text-xs font-mono"
                      />
                    </div>
                  </div>

                  <div>
                    <label className="block font-semibold text-slate-800 mb-1">
                      Contractual LPO Link
                    </label>
                    <select
                      value={createLpoId}
                      onChange={(e) => setCreateLpoId(e.target.value)}
                      className="w-full border border-slate-300 rounded px-2.5 py-1.5 bg-white text-slate-900 text-xs"
                    >
                      <option value="">No Initial LPO Link</option>
                      {lposList
                        .filter(
                          (l) =>
                            (!createProjectId || l.project_id === createProjectId) &&
                            (!createSupplierId || l.supplier_id === createSupplierId)
                        )
                        .map((l) => (
                          <option key={l.id} value={l.id}>
                            {l.lpo_number} (Cap: AED {l.total_amount_cap || 'None'})
                          </option>
                        ))}
                    </select>
                  </div>

                  <div className="pt-1">
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={createLpoRequired}
                        onChange={(e) => setCreateLpoRequired(e.target.checked)}
                        className="rounded border-slate-300 text-teal-600"
                      />
                      <span className="text-xs text-slate-700">LPO is mandatory for this case</span>
                    </label>
                  </div>
                </div>

                <div className="bg-slate-50 p-3 rounded border border-slate-200 text-[11px] text-slate-500 leading-relaxed font-mono">
                  Segregation of Duties (SoD): The account creating this case ({currentUser?.name}) will be logged as the case creator and cannot perform final review sign-off.
                </div>

                {/* Modal Footer */}
                <div className="pt-3 flex items-center justify-end gap-2 border-t border-slate-100">
                  <button
                    type="button"
                    onClick={() => setCreateWorkflow(closeCreateWorkflow(createWorkflow))}
                    className="px-3.5 py-1.5 text-xs font-medium text-slate-600 hover:text-slate-800 rounded cursor-pointer"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={isSubmittingCase}
                    className="px-4 py-1.5 text-xs font-semibold bg-slate-900 hover:bg-slate-800 text-white rounded transition-colors cursor-pointer shadow-xs disabled:bg-slate-300"
                  >
                    {isSubmittingCase ? 'Creating Case...' : 'Create Case Shell'}
                  </button>
                </div>
              </form>
            )}
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

      {/* AI-Assisted Field Review Drawer / Modal */}
      {reviewDocId && (
        <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-2xl max-w-4xl w-full max-h-[90vh] flex flex-col overflow-hidden border border-slate-200">
            {/* Modal Header */}
            <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between bg-slate-50">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-teal-600 text-white flex items-center justify-center shadow-xs">
                  <Sparkles className="w-4 h-4" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="text-sm font-bold text-slate-900">
                      AI-Assisted Field Review & Human Confirmation
                    </h3>
                    {reviewFieldsData && (
                      <span className={`text-[10px] px-2 py-0.5 rounded-full font-mono border ${
                        reviewFieldsData.data_review_status === 'CONFIRMED'
                          ? 'bg-emerald-50 text-emerald-800 border-emerald-300'
                          : 'bg-amber-50 text-amber-800 border-amber-300'
                      }`}>
                        {reviewFieldsData.data_review_status === 'CONFIRMED' ? 'HUMAN CONFIRMED' : 'UNREVIEWED / UNTRUSTED'}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-slate-500 font-mono">
                    Document: {reviewFieldsData?.original_filename || reviewDocId} ({reviewFieldsData?.doc_type})
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => handleConfirmFields(reviewDocId)}
                  disabled={isConfirmingFields || reviewFieldsData?.data_review_status === 'CONFIRMED'}
                  className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold rounded-md shadow-xs flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
                >
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  <span>{isConfirmingFields ? 'Confirming...' : 'Confirm All Fields'}</span>
                </button>
                <button
                  type="button"
                  onClick={() => setReviewDocId(null)}
                  className="p-1 text-slate-400 hover:text-slate-600 rounded-lg hover:bg-slate-100 cursor-pointer"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
            </div>

            {/* Notification Banner */}
            {extractionActionSuccess && (
              <div className="px-6 py-2 bg-emerald-50 border-b border-emerald-100 text-emerald-800 text-xs flex items-center gap-2">
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 shrink-0" />
                <span>{extractionActionSuccess}</span>
              </div>
            )}
            {extractionActionError && (
              <div className="px-6 py-2 bg-rose-50 border-b border-rose-100 text-rose-800 text-xs flex items-center gap-2">
                <AlertTriangle className="w-3.5 h-3.5 text-rose-600 shrink-0" />
                <span>{extractionActionError}</span>
              </div>
            )}

            {/* Trust Safeguard Notice */}
            <div className="px-6 py-2.5 bg-slate-50 border-b border-slate-200 text-[11px] text-slate-600 flex items-center gap-2">
              <ShieldCheck className="w-4 h-4 text-teal-600 shrink-0" />
              <span>
                <strong>Verification Safety Policy:</strong> AI-extracted values are strictly untrusted until confirmed by a qualified QS or Site Engineer. Only confirmed/corrected values are accepted by deterministic verification rules.
              </span>
            </div>

            {/* Modal Body */}
            <div className="p-6 overflow-y-auto space-y-6 flex-1">
              {isLoadingFields ? (
                <div className="py-12 text-center text-slate-400 text-xs">
                  <RefreshCw className="w-5 h-5 animate-spin mx-auto mb-2 text-teal-600" />
                  Loading extracted schema fields...
                </div>
              ) : reviewFieldsData ? (
                <>
                  {/* Header Fields Section */}
                  <div>
                    <h4 className="text-xs font-bold text-slate-900 uppercase tracking-wider mb-3 flex items-center gap-1.5">
                      <FileText className="w-3.5 h-3.5 text-slate-500" />
                      Header Fields ({reviewFieldsData.header_fields.length})
                    </h4>
                    {reviewFieldsData.header_fields.length === 0 ? (
                      <div className="p-4 bg-slate-50 rounded border border-slate-200 text-xs text-slate-500 text-center">
                        No header fields extracted yet. Click "AI Extract" to run Gemini multimodal extraction.
                      </div>
                    ) : (
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        {reviewFieldsData.header_fields.map((field) => (
                          <div
                            key={field.id}
                            className={`p-3 rounded-lg border text-xs space-y-1.5 transition-colors ${
                              field.status === 'CORRECTED'
                                ? 'bg-amber-50/40 border-amber-200'
                                : field.status === 'CONFIRMED'
                                ? 'bg-emerald-50/40 border-emerald-200'
                                : 'bg-slate-50 border-slate-200'
                            }`}
                          >
                            <div className="flex items-center justify-between">
                              <span className="font-semibold text-slate-700 font-mono capitalize">
                                {field.field_key.replace(/_/g, ' ')}
                              </span>
                              <div className="flex items-center gap-1.5">
                                <span
                                  className={`text-[9px] px-1.5 py-0.2 rounded font-mono font-bold uppercase ${
                                    field.status === 'CONFIRMED'
                                      ? 'bg-emerald-100 text-emerald-800'
                                      : field.status === 'CORRECTED'
                                      ? 'bg-purple-100 text-purple-800'
                                      : field.status === 'MISSING'
                                      ? 'bg-rose-100 text-rose-800'
                                      : 'bg-amber-100 text-amber-800'
                                  }`}
                                >
                                  {field.status}
                                </span>
                                {field.revisions_count ? (
                                  <span className="text-[9px] bg-slate-200 text-slate-600 px-1 rounded font-mono">
                                    {field.revisions_count} rev
                                  </span>
                                ) : null}
                              </div>
                            </div>

                            {editingFieldId === field.id ? (
                              <div className="space-y-2 pt-1 border-t border-slate-200">
                                <div>
                                  <label className="text-[10px] text-slate-500 block mb-0.5">Correct Value</label>
                                  <input
                                    type="text"
                                    value={editingFieldValue}
                                    onChange={(e) => setEditingFieldValue(e.target.value)}
                                    className="w-full text-xs px-2 py-1 bg-white border border-slate-300 rounded focus:outline-none focus:ring-1 focus:ring-teal-500 font-mono"
                                  />
                                </div>
                                <div>
                                  <label className="text-[10px] text-slate-500 block mb-0.5">Correction Reason</label>
                                  <input
                                    type="text"
                                    value={editingReason}
                                    onChange={(e) => setEditingReason(e.target.value)}
                                    placeholder="e.g. Scanned receipt clarification"
                                    className="w-full text-xs px-2 py-1 bg-white border border-slate-300 rounded focus:outline-none focus:ring-1 focus:ring-teal-500"
                                  />
                                </div>
                                <div className="flex items-center justify-end gap-1.5 pt-1">
                                  <button
                                    type="button"
                                    onClick={() => setEditingFieldId(null)}
                                    className="text-[10px] text-slate-500 hover:text-slate-700 px-2 py-1"
                                  >
                                    Cancel
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => handleSaveFieldCorrection(field.id)}
                                    disabled={isSavingField}
                                    className="text-[10px] font-semibold bg-teal-600 hover:bg-teal-700 text-white px-2.5 py-1 rounded shadow-xs"
                                  >
                                    {isSavingField ? 'Saving...' : 'Save Correction'}
                                  </button>
                                </div>
                              </div>
                            ) : (
                              <div className="flex items-center justify-between pt-1">
                                <div className="font-mono text-sm font-bold text-slate-900">
                                  {field.normalized_value ?? <span className="text-slate-400 italic">None / Absent</span>}
                                </div>
                                <button
                                  type="button"
                                  onClick={() => {
                                    setEditingFieldId(field.id)
                                    setEditingFieldValue(field.normalized_value || '')
                                    setEditingReason('')
                                  }}
                                  className="text-[10px] text-teal-700 hover:text-teal-900 font-medium underline cursor-pointer"
                                >
                                  Edit
                                </button>
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Line Items Section */}
                  {reviewFieldsData.line_items.length > 0 && (
                    <div className="pt-2">
                      <h4 className="text-xs font-bold text-slate-900 uppercase tracking-wider mb-3 flex items-center gap-1.5">
                        <Layers className="w-3.5 h-3.5 text-slate-500" />
                        Extracted Line Items ({reviewFieldsData.line_items.length})
                      </h4>
                      <div className="border border-slate-200 rounded-lg overflow-hidden shadow-2xs">
                        <table className="w-full text-left border-collapse text-xs">
                          <thead>
                            <tr className="bg-slate-50 border-b border-slate-200 text-slate-600 text-[11px] font-bold">
                              <th className="py-2 px-3">#</th>
                              <th className="py-2 px-3">Fields & Provenance</th>
                              <th className="py-2 px-3 text-right">Site Rejections</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-slate-100">
                            {reviewFieldsData.line_items.map((line) => (
                              <tr key={line.id} className="hover:bg-slate-50/50">
                                <td className="py-2.5 px-3 font-mono font-bold text-slate-700 align-top">
                                  Line {line.line_no}
                                </td>
                                <td className="py-2.5 px-3 space-y-1 align-top">
                                  <div className="flex flex-wrap gap-2">
                                    {line.fields.map((f) => (
                                      <div
                                        key={f.id}
                                        className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded bg-slate-100 border border-slate-200 text-[11px]"
                                      >
                                        <span className="text-slate-500 font-mono">{f.field_key}:</span>
                                        <span className="font-mono font-bold text-slate-900">
                                          {f.normalized_value ?? 'None'}
                                        </span>
                                        <span className={`text-[8px] px-1 rounded font-mono font-bold ${
                                          f.status === 'CONFIRMED'
                                            ? 'bg-emerald-200 text-emerald-800'
                                            : f.status === 'CORRECTED'
                                            ? 'bg-purple-200 text-purple-800'
                                            : 'bg-amber-200 text-amber-800'
                                        }`}>
                                          {f.status}
                                        </span>
                                      </div>
                                    ))}
                                  </div>
                                </td>
                                <td className="py-2.5 px-3 text-right font-mono align-top">
                                  {line.rejected_qty ? (
                                    <span className="text-rose-600 font-bold bg-rose-50 px-1.5 py-0.5 rounded border border-rose-200">
                                      Rejected: {line.rejected_qty}
                                    </span>
                                  ) : (
                                    <span className="text-slate-400 italic">None</span>
                                  )}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}
                </>
              ) : (
                <div className="py-12 text-center text-slate-400 text-xs">
                  Document data unavailable.
                </div>
              )}
            </div>

            {/* Modal Footer */}
            <div className="px-6 py-3 border-t border-slate-200 bg-slate-50 flex items-center justify-between text-xs text-slate-500">
              <span className="font-mono text-[11px]">
                Audited Extractor: {reviewFieldsData?.extractor_name || 'gemini-2.5-flash'}
              </span>
              <button
                type="button"
                onClick={() => setReviewDocId(null)}
                className="px-4 py-1.5 bg-slate-200 hover:bg-slate-300 text-slate-700 font-medium rounded-md cursor-pointer"
              >
                Close Review
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default App
