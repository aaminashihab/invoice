export type ReviewOutcome =
  | 'VERIFIED_NO_EXCEPTIONS'
  | 'VERIFIED_WITH_EXCEPTIONS'
  | 'ON_HOLD_QUERIED'
  | 'REJECTED'

export interface CaseValidationDetails {
  caseId: string
  hasQuantityMismatch: boolean
  hasMissingEvidence: boolean
  hasUncertainEvidence: boolean
  hasUnitIncompatible: boolean
  hasDnReuse: boolean
  dnReuseJustified?: boolean
  manualVatCheckDocumented: boolean
  vatAutomatedStatus: 'NOT_CHECKED'
}

export interface OutcomeOption {
  value: ReviewOutcome
  label: string
  allowed: boolean
  restrictionReason?: string
}

/**
 * Computes which review outcomes are permitted according to confirmed business rules
 * (D1, D2, D3, D5, D6) and Revision 3 clarifications (C1, C4, P9):
 *
 * 1. "Verified – no exceptions":
 *    - Blocked if any quantity mismatch, missing evidence, uncertain evidence,
 *      unit incompatibility, or unaddressed DN reuse exists.
 *    - Gated by manual VAT check: per P9, if automated VAT is NOT_CHECKED,
 *      manual VAT check must be documented.
 *
 * 2. "Verified with noted exceptions":
 *    - STRICTLY PREVENTED if case has a quantity mismatch (D1 exact match policy).
 *    - STRICTLY PREVENTED if case has missing required evidence (F8 evidence rule).
 *    - Permitted ONLY for approved exceptions (e.g. delivery-note reuse under C1).
 *    - Requires mandatory reviewer justification.
 *
 * 3. "On hold – queried with supplier" and "Rejected – return to supplier":
 *    - Always available when exceptions, queries, or overbilling exist.
 *    - Require reviewer note.
 */
export function getPermittedReviewOutcomes(
  details: CaseValidationDetails
): OutcomeOption[] {
  // Check conditions for "Verified – no exceptions"
  let noExceptionsAllowed = true
  let noExceptionsReason: string | undefined

  if (details.hasQuantityMismatch) {
    noExceptionsAllowed = false
    noExceptionsReason = 'Blocked: Quantity mismatch detected (D1 exact tolerance policy).'
  } else if (details.hasMissingEvidence) {
    noExceptionsAllowed = false
    noExceptionsReason = 'Blocked: Missing required document or evidence (F8 evidence rule).'
  } else if (details.hasUncertainEvidence) {
    noExceptionsAllowed = false
    noExceptionsReason = 'Blocked: Uncertain or unconfirmed extracted values present.'
  } else if (details.hasUnitIncompatible) {
    noExceptionsAllowed = false
    noExceptionsReason = 'Blocked: Incompatible units without confirmed conversion rule.'
  } else if (details.hasDnReuse) {
    noExceptionsAllowed = false
    noExceptionsReason = 'Blocked: Delivery note reuse flagged (C1 requires noted exception).'
  } else if (!details.manualVatCheckDocumented) {
    noExceptionsAllowed = false
    noExceptionsReason = 'Blocked: Automated VAT is NOT_CHECKED; requires documented manual VAT check (P9).'
  }

  // Check conditions for "Verified with noted exceptions"
  let withExceptionsAllowed = false
  let withExceptionsReason: string | undefined

  if (details.hasQuantityMismatch) {
    withExceptionsAllowed = false
    withExceptionsReason =
      'Prevented: Quantity mismatch cannot be verified with exceptions (D1 zero-tolerance rule requires supplier query or rejection).'
  } else if (details.hasMissingEvidence) {
    withExceptionsAllowed = false
    withExceptionsReason =
      'Prevented: Missing required evidence cannot be verified with exceptions (F8 requires supplier query or rejection).'
  } else if (details.hasDnReuse) {
    // Approved exception: C1 permits justified DN reuse
    withExceptionsAllowed = true
  } else {
    withExceptionsAllowed = false
    withExceptionsReason =
      'Prevented: No permitted exception applicable. Clean cases use "Verified – no exceptions".'
  }

  return [
    {
      value: 'VERIFIED_NO_EXCEPTIONS',
      label: 'Verified – no exceptions',
      allowed: noExceptionsAllowed,
      restrictionReason: noExceptionsReason,
    },
    {
      value: 'VERIFIED_WITH_EXCEPTIONS',
      label: 'Verified with noted exceptions',
      allowed: withExceptionsAllowed,
      restrictionReason: withExceptionsReason,
    },
    {
      value: 'ON_HOLD_QUERIED',
      label: 'On hold – queried with supplier',
      allowed: true,
    },
    {
      value: 'REJECTED',
      label: 'Rejected – return to supplier',
      allowed: true,
    },
  ]
}

export interface ValidationResult {
  isValid: boolean
  error?: string
}

/**
 * Validates whether a review submission complies with audit, justification,
 * and declaration safety rules. Never allows automatic payment.
 */
export function validateReviewSubmission(params: {
  outcome: ReviewOutcome
  allowedOutcomes: OutcomeOption[]
  reviewerNote: string
  declarationAccepted: boolean
}): ValidationResult {
  const selectedOption = params.allowedOutcomes.find((o) => o.value === params.outcome)

  if (!selectedOption) {
    return { isValid: false, error: 'Invalid review outcome selected.' }
  }

  if (!selectedOption.allowed) {
    return {
      isValid: false,
      error: selectedOption.restrictionReason || 'Selected outcome is not permitted for this case.',
    }
  }

  // Reviewer notes / justification requirements
  const trimmedNote = params.reviewerNote.trim()

  if (params.outcome === 'VERIFIED_WITH_EXCEPTIONS') {
    if (trimmedNote.length < 10) {
      return {
        isValid: false,
        error: 'Reviewer justification is required for permitted exceptions (minimum 10 characters).',
      }
    }
  } else if (params.outcome === 'ON_HOLD_QUERIED') {
    if (trimmedNote.length < 5) {
      return {
        isValid: false,
        error: 'Supplier query rationale is required (minimum 5 characters).',
      }
    }
  } else if (params.outcome === 'REJECTED') {
    if (trimmedNote.length < 5) {
      return {
        isValid: false,
        error: 'Rejection rationale is required (minimum 5 characters).',
      }
    }
  }

  // Safety declaration is mandatory
  if (!params.declarationAccepted) {
    return {
      isValid: false,
      error: 'Reviewer must accept the safety declaration confirming this is an audit sign-off, not a payment approval.',
    }
  }

  return { isValid: true }
}

/**
 * Formats a review outcome option label for select dropdowns.
 * Appends ' (Restricted)' for disallowed options without embedding lengthy technical reasons.
 */
export function formatOutcomeOptionLabel(option: OutcomeOption): string {
  return `${option.label}${!option.allowed ? ' (Restricted)' : ''}`
}

/**
 * Evaluates whether the review decision form has all required inputs completed,
 * determining whether the submission button should be enabled.
 */
export function isReviewDecisionSubmittable(params: {
  outcome: ReviewOutcome
  allowedOutcomes: OutcomeOption[]
  reviewerNote: string
  declarationAccepted: boolean
}): boolean {
  return validateReviewSubmission(params).isValid
}

