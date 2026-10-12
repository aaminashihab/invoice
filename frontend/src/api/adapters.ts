import type { ApiCaseDetail, ApiFinding, ApiDocument, ApiCaseLineItem, ApiCaseLineLink } from './client'
import type { ComparisonLine, AuditEvent, InvoiceRecord } from '../data/demoData'

export interface ExtendedInvoiceRecord extends InvoiceRecord {
  case_ref?: string
  documents?: ApiDocument[]
  lineItems?: ApiCaseLineItem[]
  lineLinks?: ApiCaseLineLink[]
  createdBy?: string | null
}

export const ACTOR_DISPLAY_NAMES: Record<string, string> = {
  'usr-sim-eng': 'sim-engineer',
  'usr-sim-rev': 'sim-reviewer',
  'usr-sim-qs': 'sim-qs',
  'usr-sim-acc': 'sim-accounts',
  'usr-pilot-project-qs': 'Ramesh QS (Project QS)',
  'usr-pilot-pm-reviewer': 'David PM (Commercial PM)',
  'usr-pilot-site-eng': 'Ahmed Eng (Site Engineer)',
  'usr-pilot-storekeeper': 'Tariq Store (Storekeeper)',
  'usr-pilot-director-khalfan': 'Khalfan Director (Commercial Director)',
}

const USER_AUDIT_ACTIONS = new Set([
  'DOCUMENT_UPLOADED',
  'DOCUMENT_DELETED',
  'DOCUMENT_SUPERSEDED',
  'REVIEW_RECORDED',
])

export function resolveAuditActor(action: string, actorId?: string | null): string {
  if (actorId) {
    return ACTOR_DISPLAY_NAMES[actorId] || actorId
  }
  if (USER_AUDIT_ACTIONS.has(action)) {
    return 'Unknown actor'
  }
  return 'System'
}

export function mapCaseToInvoiceRecord(
  c: ApiCaseDetail,
  fallbackAmount = '45,200.00'
): ExtendedInvoiceRecord {
  const latestRun =
    c.runs && c.runs.length > 0
      ? [...c.runs].sort((a, b) => (b.run_no ?? 0) - (a.run_no ?? 0))[0]
      : undefined
  const findings: ApiFinding[] = latestRun?.findings || []

  const hasQuantityMismatch = findings.some(
    (f) =>
      f.outcome === 'MISMATCH' &&
      (f.category === 'QTY_LINE' || f.category === 'QTY_TOTAL' || f.rule_code.includes('QTY'))
  )
  const hasMissingEvidence = findings.some((f) => f.outcome === 'MISSING_EVIDENCE')
  const hasUncertainEvidence = findings.some((f) => f.outcome === 'UNCERTAIN')
  const hasUnitIncompatible = findings.some(
    (f) => f.outcome === 'UNIT_INCOMPATIBLE' || (f.category === 'UNIT' && f.outcome === 'MISMATCH')
  )
  const dnReuseFinding = findings.find(
    (f) => f.category === 'DN_REUSE' || f.rule_code.startsWith('DN_REUSE')
  )
  const hasDnReuse = Boolean(dnReuseFinding)

  let dnReuseDetails: InvoiceRecord['dnReuseDetails'] = undefined
  if (dnReuseFinding) {
    const details = dnReuseFinding.details || {}
    dnReuseDetails = {
      otherCaseId: String(details.other_case_ref || 'VC-2026-00012'),
      otherCaseStatus: String(details.other_case_status || 'Reviewed'),
      dnNumber: String(dnReuseFinding.subject_id || 'DN-7019'),
    }
  }

  // Dynamic calculation from recorded invoice lines when available
  let calculatedAmount: string | null = null
  const invoiceLines = (c.line_items || []).filter((l) => l.doc_type === 'INVOICE')
  if (invoiceLines.length > 0) {
    const total = invoiceLines.reduce((sum, li) => {
      const lineAmt = parseFloat(li.fields?.line_amount || '0')
      if (!isNaN(lineAmt) && lineAmt > 0) {
        return sum + lineAmt
      }
      const qty = parseFloat(li.fields?.invoiced_qty || '0')
      const price = parseFloat(li.fields?.unit_price || '0')
      if (!isNaN(qty) && !isNaN(price) && qty > 0 && price > 0) {
        return sum + (qty * price)
      }
      return sum
    }, 0)
    if (total > 0) {
      calculatedAmount = total.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    }
  }

  // Baseline synthetic display values used as fallback when line items are not yet populated
  const CASE_AMOUNTS: Record<string, string> = {
    'INV-8821': '45,200.00',
    'INV-9042': '18,750.00',
    'INV-3104': '92,400.00',
    'INV-1290': '12,300.00',
    'INV-7719': '8,450.00',
    'INV-HIST-110': '14,200.00',
    'VC-2026-00001': '45,200.00',
    'VC-2026-00002': '18,750.00',
    'VC-2026-00003': '92,400.00',
    'VC-2026-00004': '12,300.00',
    'VC-2026-00005': '8,450.00',
    'VC-2026-00012': '14,200.00',
  }
  const resolvedAmount =
    calculatedAmount ||
    (c.invoice_number_hint && CASE_AMOUNTS[c.invoice_number_hint]) ||
    (c.case_ref && CASE_AMOUNTS[c.case_ref]) ||
    fallbackAmount

  // Derive verification status (automated check outcome)
  let verificationStatus: InvoiceRecord['status'] = 'Pending'
  if (findings.length > 0) {
    if (hasQuantityMismatch || hasUnitIncompatible || hasDnReuse) {
      verificationStatus = 'Mismatch'
    } else if (hasMissingEvidence) {
      verificationStatus = 'Missing'
    } else if (hasUncertainEvidence) {
      verificationStatus = 'Uncertain'
    } else {
      verificationStatus = 'Matched'
    }
  } else if (latestRun) {
    verificationStatus = 'Matched'
  } else {
    verificationStatus = 'Pending'
  }

  // Derive review outcome (human review decision)
  let reviewOutcome = 'Awaiting Review'
  const latestReview = c.reviews && c.reviews.length > 0 ? c.reviews[c.reviews.length - 1] : undefined
  if (latestReview) {
    switch (latestReview.outcome) {
      case 'VERIFIED_CLEAN':
        reviewOutcome = 'Verified (Clean Match)'
        break
      case 'VERIFIED_WITH_EXCEPTIONS':
        reviewOutcome = 'Verified (With Exceptions)'
        break
      case 'ON_HOLD_QUERIED':
        reviewOutcome = 'On Hold (Queried)'
        break
      case 'REJECTED':
        reviewOutcome = 'Rejected'
        break
      default:
        reviewOutcome = latestReview.outcome
    }
  } else if (c.status === 'READY_TO_VERIFY') {
    reviewOutcome = 'Ready to Verify'
  } else if (c.status === 'PENDING') {
    reviewOutcome = 'Pending Verification'
  } else if (c.status === 'VERIFIED_AWAITING_REVIEW') {
    reviewOutcome = 'Awaiting Review'
  } else if (c.status === 'VERIFIED_NO_EXCEPTIONS') {
    reviewOutcome = 'Verified (Clean Match)'
  } else if (c.status === 'VERIFIED_WITH_EXCEPTIONS') {
    reviewOutcome = 'Verified (With Exceptions)'
  } else if (c.status === 'ON_HOLD_QUERIED') {
    reviewOutcome = 'On Hold (Queried)'
  } else if (c.status === 'REJECTED') {
    reviewOutcome = 'Rejected'
  }

  // Backwards compatibility: status reflects automated verification status
  const status: InvoiceRecord['status'] = verificationStatus

  // Delivery notes list from documents
  const dns = (c.documents || [])
    .filter((d) => d.doc_type === 'DELIVERY_NOTE')
    .map((d) => d.reference_no_normalized ? `DN-${d.reference_no_normalized}` : d.original_filename)

  // Comparison lines
  const lines: ComparisonLine[] = []
  const quantityFindings = findings.filter(
    (f) => f.category === 'QTY_LINE' || f.category === 'QTY_TOTAL' || f.category === 'COMPLETENESS' || f.category === 'LPO'
  )

  for (const f of quantityFindings) {
    let lineStatus: ComparisonLine['status'] = 'Matched'
    if (f.outcome === 'MISMATCH') lineStatus = 'Mismatch'
    else if (f.outcome === 'MISSING_EVIDENCE') lineStatus = 'Missing'
    else if (f.outcome === 'UNCERTAIN') lineStatus = 'Uncertain'

    let invQty = f.actual || '—'
    let dnQty = f.expected || '—'

    // Determine correct quantity direction:
    // In backend verification engine:
    // - For QTY_001 (missing evidence) and COMP_002: expected_value is invoiced qty, actual_value is delivered qty ("0" or null).
    // - For QTY_004 (overbilling / mismatch) & seed QTY_002: actual_value is invoiced qty, expected_value is accepted delivered qty.
    // - For QTY_003 / clean match: actual_value and expected_value are identical.
    if (f.outcome === 'MISSING_EVIDENCE' || (f.rule_code === 'QTY_001' && f.outcome !== 'MATCH')) {
      invQty = f.expected || '—'
      dnQty = f.actual && f.actual !== '0' ? f.actual : '0.000'
    } else if (f.rule_code === 'QTY_004' || f.rule_code === 'QTY_002') {
      invQty = f.actual || '—'
      dnQty = f.expected || '—'
    }

    lines.push({
      item: f.message || f.subject_type || 'Material',
      invQty,
      unit: f.unit || '',
      dnQty,
      diff: f.difference || (lineStatus === 'Matched' ? '0.000' : '—'),
      status: lineStatus,
      dnRef: dns.length > 0 ? dns.join(', ') : '—',
      rejectionEvidence: f.message.includes('rejection') ? 'Documented on DN ticket' : undefined,
      ruleStatus: f.rule_status || 'CONFIRMED',
    })
  }

  if (lines.length === 0) {
    const invLines = (c.line_items || []).filter((l) => l.doc_type === 'INVOICE')
    const fallbackLineStatus =
      status === 'Mismatch' ? 'Mismatch' : status === 'Missing' ? 'Missing' : 'Pending'

    if (invLines.length > 0) {
      for (const li of invLines) {
        const links = (c.line_links || []).filter((link) => link.invoice_line_id === li.id)
        let deliveredSum = 0
        let hasLinked = false
        for (const link of links) {
          const dnLine = (c.line_items || []).find((l) => l.id === link.dn_line_id)
          if (dnLine && dnLine.fields?.delivered_qty) {
            hasLinked = true
            deliveredSum += parseFloat(dnLine.fields.delivered_qty) || 0
          }
        }
        lines.push({
          item: li.fields?.description || `Invoice Line ${li.line_no}`,
          invQty: li.fields?.invoiced_qty || '—',
          unit: li.fields?.unit || '',
          dnQty: hasLinked ? deliveredSum.toFixed(3) : '—',
          diff: '—',
          status: fallbackLineStatus,
          dnRef: dns.length > 0 ? dns.join(', ') : 'None',
          ruleStatus: 'CONFIRMED',
        })
      }
    } else {
      lines.push({
        item: 'Material Item Verification',
        invQty: '—',
        unit: '',
        dnQty: '—',
        diff: '—',
        status: fallbackLineStatus,
        dnRef: dns.length > 0 ? dns.join(', ') : 'None',
        ruleStatus: 'CONFIRMED',
      })
    }
  }

  // Audit history
  const auditHistory: AuditEvent[] = []

  // Add reviews first
  for (const rev of c.reviews || []) {
    const qualifiersText = rev.qualifiers?.length ? ` [Qualifiers: ${rev.qualifiers.join(', ')}]` : ''
    auditHistory.push({
      id: rev.id,
      time: rev.created_at ? rev.created_at.substring(11, 19) : '00:00:00',
      title: `Review Recorded: ${rev.outcome}`,
      detail: `${rev.comment}${qualifiersText}`,
      actor: rev.reviewer_name || rev.reviewer_id || 'sim-reviewer',
      type: 'REVIEW',
    })
  }

  // Add audit events
  for (const a of c.audit_events || []) {
    let title = a.action
    let type: AuditEvent['type'] = 'SYSTEM'
    let permanent = false

    if (a.action === 'DN_REUSE_FLAGGED') {
      title = 'Delivery Note Reuse Flagged'
      type = 'DN_REUSE'
      permanent = true
    } else if (a.action === 'VERIFICATION_RUN_COMPLETED') {
      title = 'Verification Run Completed'
      type = 'RUN'
    } else if (a.action === 'REVIEW_RECORDED') {
      title = 'Review Recorded'
      type = 'REVIEW'
    } else if (a.action === 'DOCUMENT_UPLOADED') {
      title = 'Document Uploaded'
      type = 'SYSTEM'
    } else if (a.action === 'DOCUMENT_DELETED') {
      title = 'Document Deleted'
      type = 'SYSTEM'
    } else if (a.action === 'DOCUMENT_SUPERSEDED') {
      title = 'Document Superseded'
      type = 'SYSTEM'
    } else if (a.action === 'TEST_CUSTOM_AUDIT_ACTION') {
      title = 'Custom Audit Action (Test Fixture)'
      type = 'SYSTEM'
    }

    const detail = a.after_state
      ? Object.entries(a.after_state)
          .map(([k, v]) => `${k}: ${v}`)
          .join('; ')
      : `Audit event for ${a.entity_type}`

    auditHistory.push({
      id: a.id,
      time: a.at ? a.at.substring(11, 19) : '00:00:00',
      title,
      detail,
      actor: resolveAuditActor(a.action, a.actor_id),
      type,
      permanent,
    })
  }

  return {
    id: c.id,
    case_ref: c.case_ref,
    supplier: c.supplier.name,
    supplierTrn: c.supplier.trn,
    invoiceNo: c.invoice_number_hint || c.case_ref,
    project: c.project.name,
    amountAed: resolvedAmount,
    status,
    verificationStatus,
    reviewOutcome,
    date: c.created_at ? c.created_at.substring(0, 10) : '2026-03-28',
    dns: dns.length > 0 ? dns : ['No delivery notes attached'],
    lpoRef: c.lpo_required
      ? ((c.documents || []).some((d) => d.doc_type === 'LPO') ? 'LPO Attached' : 'Missing (Required)')
      : (c.lpo_reason_code || 'Not Required'),
    hasQuantityMismatch,
    hasMissingEvidence,
    hasUncertainEvidence,
    hasUnitIncompatible,
    hasDnReuse,
    dnReuseDetails,
    lines,
    auditHistory,
    documents: c.documents || [],
    lineItems: c.line_items || [],
    lineLinks: c.line_links || [],
    createdBy: c.created_by,
  }
}
