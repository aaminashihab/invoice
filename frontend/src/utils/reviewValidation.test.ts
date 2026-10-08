import { describe, it, expect } from 'vitest'
import {
  getPermittedReviewOutcomes,
  validateReviewSubmission,
  formatOutcomeOptionLabel,
  isReviewDecisionSubmittable,
  type CaseValidationDetails,
} from './reviewValidation'

describe('Review Validation Rules (M1 Front-end Verification)', () => {
  it('prevents "Verified with noted exceptions" when case has a quantity mismatch', () => {
    const details: CaseValidationDetails = {
      caseId: 'case-02',
      hasQuantityMismatch: true,
      hasMissingEvidence: false,
      hasUncertainEvidence: false,
      hasUnitIncompatible: false,
      hasDnReuse: false,
      manualVatCheckDocumented: true,
      vatAutomatedStatus: 'NOT_CHECKED',
    }

    const outcomes = getPermittedReviewOutcomes(details)

    const noExceptions = outcomes.find((o) => o.value === 'VERIFIED_NO_EXCEPTIONS')
    const withExceptions = outcomes.find((o) => o.value === 'VERIFIED_WITH_EXCEPTIONS')
    const onHold = outcomes.find((o) => o.value === 'ON_HOLD_QUERIED')
    const rejected = outcomes.find((o) => o.value === 'REJECTED')

    expect(noExceptions?.allowed).toBe(false)
    expect(noExceptions?.restrictionReason).toContain('Quantity mismatch detected')

    // Must be prevented per D1 exact tolerance policy!
    expect(withExceptions?.allowed).toBe(false)
    expect(withExceptions?.restrictionReason).toContain('Quantity mismatch cannot be verified with exceptions')

    // Allowed options
    expect(onHold?.allowed).toBe(true)
    expect(rejected?.allowed).toBe(true)
  })

  it('prevents "Verified with noted exceptions" when case has missing required evidence', () => {
    const details: CaseValidationDetails = {
      caseId: 'case-03',
      hasQuantityMismatch: false,
      hasMissingEvidence: true,
      hasUncertainEvidence: false,
      hasUnitIncompatible: false,
      hasDnReuse: false,
      manualVatCheckDocumented: true,
      vatAutomatedStatus: 'NOT_CHECKED',
    }

    const outcomes = getPermittedReviewOutcomes(details)

    const noExceptions = outcomes.find((o) => o.value === 'VERIFIED_NO_EXCEPTIONS')
    const withExceptions = outcomes.find((o) => o.value === 'VERIFIED_WITH_EXCEPTIONS')

    expect(noExceptions?.allowed).toBe(false)
    expect(withExceptions?.allowed).toBe(false)
    expect(withExceptions?.restrictionReason).toContain('Missing required evidence cannot be verified with exceptions')
  })

  it('permits "Verified with noted exceptions" ONLY for approved exceptions like DN reuse (C1)', () => {
    const details: CaseValidationDetails = {
      caseId: 'case-04',
      hasQuantityMismatch: false,
      hasMissingEvidence: false,
      hasUncertainEvidence: false,
      hasUnitIncompatible: false,
      hasDnReuse: true,
      manualVatCheckDocumented: true,
      vatAutomatedStatus: 'NOT_CHECKED',
    }

    const outcomes = getPermittedReviewOutcomes(details)

    const noExceptions = outcomes.find((o) => o.value === 'VERIFIED_NO_EXCEPTIONS')
    const withExceptions = outcomes.find((o) => o.value === 'VERIFIED_WITH_EXCEPTIONS')

    // "Verified - no exceptions" is blocked due to DN reuse finding
    expect(noExceptions?.allowed).toBe(false)

    // "Verified with noted exceptions" is PERMITTED under C1
    expect(withExceptions?.allowed).toBe(true)
  })

  it('requires reviewer justification for permitted exceptions', () => {
    const outcomes = getPermittedReviewOutcomes({
      caseId: 'case-04',
      hasQuantityMismatch: false,
      hasMissingEvidence: false,
      hasUncertainEvidence: false,
      hasUnitIncompatible: false,
      hasDnReuse: true,
      manualVatCheckDocumented: true,
      vatAutomatedStatus: 'NOT_CHECKED',
    })

    // Missing / empty note
    const emptyResult = validateReviewSubmission({
      outcome: 'VERIFIED_WITH_EXCEPTIONS',
      allowedOutcomes: outcomes,
      reviewerNote: '',
      declarationAccepted: true,
    })
    expect(emptyResult.isValid).toBe(false)
    expect(emptyResult.error).toContain('justification is required')

    // Short note
    const shortResult = validateReviewSubmission({
      outcome: 'VERIFIED_WITH_EXCEPTIONS',
      allowedOutcomes: outcomes,
      reviewerNote: 'ok',
      declarationAccepted: true,
    })
    expect(shortResult.isValid).toBe(false)
    expect(shortResult.error).toContain('minimum 10 characters')

    // Valid justification
    const validResult = validateReviewSubmission({
      outcome: 'VERIFIED_WITH_EXCEPTIONS',
      allowedOutcomes: outcomes,
      reviewerNote: 'DN reuse justified: verified against master subcontract agreement sub-job 4.',
      declarationAccepted: true,
    })
    expect(validResult.isValid).toBe(true)
  })

  it('enforces mandatory safety declaration (never approves payment automatically)', () => {
    const outcomes = getPermittedReviewOutcomes({
      caseId: 'case-01',
      hasQuantityMismatch: false,
      hasMissingEvidence: false,
      hasUncertainEvidence: false,
      hasUnitIncompatible: false,
      hasDnReuse: false,
      manualVatCheckDocumented: true,
      vatAutomatedStatus: 'NOT_CHECKED',
    })

    const noDeclarationResult = validateReviewSubmission({
      outcome: 'VERIFIED_NO_EXCEPTIONS',
      allowedOutcomes: outcomes,
      reviewerNote: '',
      declarationAccepted: false,
    })

    expect(noDeclarationResult.isValid).toBe(false)
    expect(noDeclarationResult.error).toContain('not a payment approval')
  })

  it('blocks "Verified – no exceptions" if automated VAT is NOT_CHECKED and manual VAT check is missing', () => {
    const outcomes = getPermittedReviewOutcomes({
      caseId: 'case-01',
      hasQuantityMismatch: false,
      hasMissingEvidence: false,
      hasUncertainEvidence: false,
      hasUnitIncompatible: false,
      hasDnReuse: false,
      manualVatCheckDocumented: false, // NOT checked yet
      vatAutomatedStatus: 'NOT_CHECKED',
    })

    const noExceptions = outcomes.find((o) => o.value === 'VERIFIED_NO_EXCEPTIONS')
    expect(noExceptions?.allowed).toBe(false)
    expect(noExceptions?.restrictionReason).toContain('requires documented manual VAT check')
  })

  describe('Review-Screen UX Polish', () => {
    const cleanCaseOutcomes = getPermittedReviewOutcomes({
      caseId: 'case-01',
      hasQuantityMismatch: false,
      hasMissingEvidence: false,
      hasUncertainEvidence: false,
      hasUnitIncompatible: false,
      hasDnReuse: false,
      manualVatCheckDocumented: true,
      vatAutomatedStatus: 'NOT_CHECKED',
    })

    const exceptionCaseOutcomes = getPermittedReviewOutcomes({
      caseId: 'case-04',
      hasQuantityMismatch: false,
      hasMissingEvidence: false,
      hasUncertainEvidence: false,
      hasUnitIncompatible: false,
      hasDnReuse: true,
      manualVatCheckDocumented: true,
      vatAutomatedStatus: 'NOT_CHECKED',
    })

    const mismatchCaseOutcomes = getPermittedReviewOutcomes({
      caseId: 'case-02',
      hasQuantityMismatch: true,
      hasMissingEvidence: false,
      hasUncertainEvidence: false,
      hasUnitIncompatible: false,
      hasDnReuse: false,
      manualVatCheckDocumented: true,
      vatAutomatedStatus: 'NOT_CHECKED',
    })

    it('disables review submission when mandatory declaration is unchecked', () => {
      const submittable = isReviewDecisionSubmittable({
        outcome: 'VERIFIED_NO_EXCEPTIONS',
        allowedOutcomes: cleanCaseOutcomes,
        reviewerNote: 'All checks verified.',
        declarationAccepted: false, // Unchecked!
      })
      expect(submittable).toBe(false)
    })

    it('disables review submission when required reviewer notes are missing or too short', () => {
      // Empty note for outcome requiring notes
      const emptyNoteSubmittable = isReviewDecisionSubmittable({
        outcome: 'VERIFIED_WITH_EXCEPTIONS',
        allowedOutcomes: exceptionCaseOutcomes,
        reviewerNote: '',
        declarationAccepted: true,
      })
      expect(emptyNoteSubmittable).toBe(false)

      // Short note (< 10 chars) for VERIFIED_WITH_EXCEPTIONS
      const shortNoteSubmittable = isReviewDecisionSubmittable({
        outcome: 'VERIFIED_WITH_EXCEPTIONS',
        allowedOutcomes: exceptionCaseOutcomes,
        reviewerNote: 'Too short',
        declarationAccepted: true,
      })
      expect(shortNoteSubmittable).toBe(false)

      // Short note (< 5 chars) for ON_HOLD_QUERIED
      const shortHoldSubmittable = isReviewDecisionSubmittable({
        outcome: 'ON_HOLD_QUERIED',
        allowedOutcomes: mismatchCaseOutcomes,
        reviewerNote: 'Hold',
        declarationAccepted: true,
      })
      expect(shortHoldSubmittable).toBe(false)
    })

    it('disables review submission when selected outcome is not permitted for the case', () => {
      const disallowedSubmittable = isReviewDecisionSubmittable({
        outcome: 'VERIFIED_WITH_EXCEPTIONS',
        allowedOutcomes: mismatchCaseOutcomes, // D1 mismatch case: exceptions disallowed!
        reviewerNote: 'Attempting to override mismatch with justification',
        declarationAccepted: true,
      })
      expect(disallowedSubmittable).toBe(false)
    })

    it('enables review submission when required fields and declaration are valid', () => {
      // Clean case verified
      const cleanSubmittable = isReviewDecisionSubmittable({
        outcome: 'VERIFIED_NO_EXCEPTIONS',
        allowedOutcomes: cleanCaseOutcomes,
        reviewerNote: '', // Note is optional for clean match
        declarationAccepted: true,
      })
      expect(cleanSubmittable).toBe(true)

      // Permitted exception with valid note
      const exceptionSubmittable = isReviewDecisionSubmittable({
        outcome: 'VERIFIED_WITH_EXCEPTIONS',
        allowedOutcomes: exceptionCaseOutcomes,
        reviewerNote: 'Replacement ticket verified under approved master subcontract C1.',
        declarationAccepted: true,
      })
      expect(exceptionSubmittable).toBe(true)

      // On hold query with valid note
      const holdSubmittable = isReviewDecisionSubmittable({
        outcome: 'ON_HOLD_QUERIED',
        allowedOutcomes: mismatchCaseOutcomes,
        reviewerNote: 'Supplier queried regarding 3.000 m3 overbilling.',
        declarationAccepted: true,
      })
      expect(holdSubmittable).toBe(true)
    })

    it('formats restricted dropdown outcomes as "(Restricted)" without long technical reason', () => {
      const restrictedOption = mismatchCaseOutcomes.find((o) => o.value === 'VERIFIED_WITH_EXCEPTIONS')!
      expect(restrictedOption.allowed).toBe(false)

      const formattedLabel = formatOutcomeOptionLabel(restrictedOption)
      expect(formattedLabel).toBe('Verified with noted exceptions (Restricted)')
      expect(formattedLabel).not.toContain('D1 zero-tolerance')
      expect(formattedLabel).not.toContain('Prevented:')
    })

    it('formats allowed dropdown outcomes without suffix', () => {
      const allowedOption = mismatchCaseOutcomes.find((o) => o.value === 'ON_HOLD_QUERIED')!
      expect(allowedOption.allowed).toBe(true)

      const formattedLabel = formatOutcomeOptionLabel(allowedOption)
      expect(formattedLabel).toBe('On hold – queried with supplier')
      expect(formattedLabel).not.toContain('(Restricted)')
    })

    it('preserves detailed rule explanations in restrictionReason for dedicated callouts', () => {
      const restrictedOption = mismatchCaseOutcomes.find((o) => o.value === 'VERIFIED_WITH_EXCEPTIONS')!
      expect(restrictedOption.restrictionReason).toContain('D1 zero-tolerance rule')
      expect(restrictedOption.restrictionReason).toContain('Quantity mismatch cannot be verified with exceptions')
    })
  })
})
