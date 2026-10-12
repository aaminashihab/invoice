import { describe, it, expect } from 'vitest'
import { mapCaseToInvoiceRecord } from './adapters'
import { getDocumentContentUrl, ApiError, type ApiCaseDetail } from './client'

describe('Frontend API Adapters and Client (Phase 1 & Phase 2)', () => {
  it('constructs correct document content URL', () => {
    const url = getDocumentContentUrl('doc-c1-inv')
    expect(url).toBe('/api/v1/documents/doc-c1-inv/content')
  })

  it('instantiates ApiError with code, status and details', () => {
    const err = new ApiError('Duplicate document in case', 'DUPLICATE_DOCUMENT_IN_CASE', 409, { filename: 'test.pdf' })
    expect(err.name).toBe('ApiError')
    expect(err.code).toBe('DUPLICATE_DOCUMENT_IN_CASE')
    expect(err.status).toBe(409)
    expect(err.message).toBe('Duplicate document in case')
    expect(err.details).toEqual({ filename: 'test.pdf' })
  })

  it('maps a clean match case to Matched invoice record', () => {
    const rawCase: ApiCaseDetail = {
      id: 'case-synth-01',
      case_ref: 'VC-2026-00001',
      project: { code: 'PRJ-CT4', name: 'Alpha Horizon Tower Phase 1' },
      supplier: { name: 'Caelum Bulk Cement Factory LLC (Fictional Demo)', trn: '100023456700003' },
      invoice_number_hint: 'INV-8821',
      currency: 'AED',
      lpo_required: true,
      status: 'VERIFIED_AWAITING_REVIEW',
      created_at: '2026-03-28T09:00:00Z',
      documents: [
        {
          id: 'doc-c1-inv',
          doc_type: 'INVOICE',
          original_filename: 'INV-8821.pdf',
          reference_no_normalized: '8821',
        },
        {
          id: 'doc-c1-dn4401',
          doc_type: 'DELIVERY_NOTE',
          original_filename: 'DN-4401.pdf',
          reference_no_normalized: '4401',
        },
      ],
      runs: [
        {
          id: 'run-c1-01',
          run_no: 1,
          summary: 'No discrepancies found in performed checks',
          summary_labels: ['No discrepancies found in performed checks', 'Some checks not performed (UAE VAT)'],
          findings: [
            {
              id: 'fnd-c1-01',
              category: 'QTY_TOTAL',
              rule_code: 'QTY_001',
              outcome: 'MATCH',
              severity: 'INFO',
              message: 'Ordinary Portland Cement: exact match of 40.000 t.',
              expected: '40.000',
              actual: '40.000',
              difference: '0.000',
              unit: 't',
            },
          ],
        },
      ],
      audit_events: [
        {
          id: 'aud-1',
          action: 'VERIFICATION_RUN_COMPLETED',
          at: '2026-03-28T10:00:00Z',
          entity_type: 'VERIFICATION_RUN',
        },
      ],
      reviews: [],
    }

    const mapped = mapCaseToInvoiceRecord(rawCase)
    expect(mapped.id).toBe('case-synth-01')
    expect(mapped.supplier).toContain('Caelum Bulk Cement')
    expect(mapped.status).toBe('Matched')
    expect(mapped.hasQuantityMismatch).toBe(false)
    expect(mapped.hasMissingEvidence).toBe(false)
    expect(mapped.hasDnReuse).toBe(false)
    expect(mapped.dns).toContain('DN-4401')
    expect(mapped.lines.length).toBeGreaterThan(0)
    expect(mapped.lines[0].status).toBe('Matched')
    expect(mapped.auditHistory.length).toBe(1)
  })

  it('maps a quantity mismatch case and flags hasQuantityMismatch', () => {
    const rawCase: ApiCaseDetail = {
      id: 'case-synth-02',
      case_ref: 'VC-2026-00002',
      project: { code: 'PRJ-MG2', name: 'Azure Bay Tower 2' },
      supplier: { name: 'Gulf ReadyMix Concrete LLC (Synthetic)', trn: '100234567800003' },
      invoice_number_hint: 'INV-9042',
      currency: 'AED',
      lpo_required: true,
      status: 'VERIFIED_AWAITING_REVIEW',
      created_at: '2026-03-29T10:00:00Z',
      documents: [],
      runs: [
        {
          id: 'run-c2-01',
          run_no: 1,
          summary: 'Discrepancies found',
          summary_labels: ['Discrepancies found'],
          findings: [
            {
              id: 'fnd-c2-01',
              category: 'QTY_LINE',
              rule_code: 'QTY_002',
              outcome: 'MISMATCH',
              severity: 'CRITICAL',
              message: 'Concrete C40/20: Invoiced 24.000 m³ exceeds delivered 21.000 m³.',
              expected: '21.000',
              actual: '24.000',
              difference: '+3.000',
              unit: 'm3',
            },
          ],
        },
      ],
      audit_events: [],
      reviews: [],
    }

    const mapped = mapCaseToInvoiceRecord(rawCase)
    expect(mapped.status).toBe('Mismatch')
    expect(mapped.hasQuantityMismatch).toBe(true)
    expect(mapped.lines[0].status).toBe('Mismatch')
    expect(mapped.lines[0].diff).toBe('+3.000')
  })

  it('maps delivery note reuse finding with permanent C1 details and historical reviews', () => {
    const rawCase: ApiCaseDetail = {
      id: 'case-synth-04',
      case_ref: 'VC-2026-00004',
      project: { code: 'PRJ-JBV', name: 'Palm Crest Villa 12' },
      supplier: { name: 'Apex Blocks & Pavers LLC (Synthetic)', trn: '100567890100003' },
      invoice_number_hint: 'INV-1290',
      currency: 'AED',
      lpo_required: false,
      status: 'VERIFIED_AWAITING_REVIEW',
      created_at: '2026-03-31T16:00:00Z',
      documents: [],
      runs: [
        {
          id: 'run-c4-01',
          run_no: 1,
          summary: 'Discrepancies found',
          summary_labels: ['Discrepancies found', 'DN reuse flagged'],
          findings: [
            {
              id: 'fnd-c4-01',
              category: 'DN_REUSE',
              rule_code: 'DN_REUSE_001',
              outcome: 'MISMATCH',
              severity: 'CRITICAL',
              message: 'DN-7019 reuse detected against case VC-2026-00012.',
              subject_id: 'DN-7019',
              details: {
                other_case_ref: 'VC-2026-00012',
                other_case_status: 'Reviewed',
              },
            },
          ],
        },
      ],
      audit_events: [
        {
          id: 'aud-4',
          action: 'DN_REUSE_FLAGGED',
          at: '2026-03-31T16:10:00Z',
          entity_type: 'DELIVERY_NOTE',
          after_state: { conflict: 'VC-2026-00012' },
        },
      ],
      reviews: [
        {
          id: 'rev-c4-01',
          run_id: 'run-c4-01',
          reviewer_id: 'usr-sim-rev',
          reviewer_name: 'Simulated Reviewer',
          outcome: 'VERIFIED_WITH_EXCEPTIONS',
          comment: 'Approved replacement ticket under C1.',
          declaration_accepted: true,
          qualifiers: ['Automated VAT: NOT_CHECKED'],
          created_at: '2026-04-01T10:00:00Z',
          dispositions: [
            {
              id: 'disp-1',
              finding_id: 'fnd-c4-01',
              disposition: 'REUSE_JUSTIFIED',
              comment: 'Approved replacement ticket under C1.',
            },
          ],
        },
      ],
    }

    const mapped = mapCaseToInvoiceRecord(rawCase)
    expect(mapped.hasDnReuse).toBe(true)
    expect(mapped.dnReuseDetails?.otherCaseId).toBe('VC-2026-00012')
    expect(mapped.dnReuseDetails?.dnNumber).toBe('DN-7019')

    // Verifies reviews and audit events in history
    expect(mapped.auditHistory.length).toBe(2)
    const revItem = mapped.auditHistory.find((a) => a.type === 'REVIEW')
    expect(revItem).toBeDefined()
    expect(revItem?.title).toContain('VERIFIED_WITH_EXCEPTIONS')
    expect(revItem?.detail).toContain('Approved replacement ticket under C1')

    const dnItem = mapped.auditHistory.find((a) => a.type === 'DN_REUSE')
    expect(dnItem).toBeDefined()
    expect(dnItem?.permanent).toBe(true)
  })

  it('sets fallback line comparison difference to "—" when no quantities are evaluated', () => {
    const rawCase: ApiCaseDetail = {
      id: 'case-synth-05',
      case_ref: 'VC-2026-00005',
      project: { code: 'PRJ-HV1', name: 'Horizon Valley Villa 4' },
      supplier: { name: 'Delta Building Materials LLC (Synthetic)', trn: '100456789000003' },
      invoice_number_hint: 'INV-3310',
      currency: 'AED',
      lpo_required: true,
      status: 'AWAITING_DOCUMENTS',
      created_at: '2026-04-02T08:00:00Z',
      documents: [],
      runs: [],
      audit_events: [],
      reviews: [],
    }

    const mapped = mapCaseToInvoiceRecord(rawCase)
    expect(mapped.lines.length).toBe(1)
    expect(mapped.lines[0].item).toBe('Material Item Verification')
    expect(mapped.lines[0].diff).toBe('—')
    expect(mapped.lines[0].invQty).toBe('—')
    expect(mapped.lines[0].dnQty).toBe('—')
    expect(mapped.lines[0].status).toBe('Pending')
  })

  it('preserves complete verification finding message without colon truncation', () => {
    const rawCase: ApiCaseDetail = {
      id: 'case-synth-lpo-msg',
      case_ref: 'VC-2026-LPO-01',
      project: { code: 'PRJ-LPO', name: 'LPO Test Tower' },
      supplier: { name: 'Steel Supply LLC', trn: '100999999900003' },
      currency: 'AED',
      lpo_required: false,
      status: 'VERIFIED_AWAITING_REVIEW',
      created_at: '2026-04-02T08:00:00Z',
      runs: [
        {
          id: 'run-lpo-01',
          run_no: 1,
          summary: 'Completed with notes',
          summary_labels: ['Completed with notes'],
          findings: [
            {
              id: 'fnd-lpo-01',
              category: 'LPO',
              rule_code: 'LPO_001',
              outcome: 'NOT_APPLICABLE',
              severity: 'INFO',
              message: 'LPO check not applicable for this invoice case (Reason: Direct site procurement below threshold).',
            },
          ],
        },
      ],
      documents: [],
      audit_events: [],
      reviews: [],
    }

    const mapped = mapCaseToInvoiceRecord(rawCase)
    expect(mapped.lines.length).toBe(1)
    expect(mapped.lines[0].item).toBe(
      'LPO check not applicable for this invoice case (Reason: Direct site procurement below threshold).'
    )
  })

  it('correctly maps audit event actors with appropriate display names and fallbacks', () => {
    const rawCase: ApiCaseDetail = {
      id: 'case-synth-test-actors',
      case_ref: 'VC-2026-00099',
      project: { code: 'PRJ-TEST', name: 'Test Project' },
      supplier: { name: 'Test Supplier', trn: '100000000000003' },
      invoice_number_hint: 'INV-TEST',
      currency: 'AED',
      lpo_required: false,
      status: 'VERIFIED_AWAITING_REVIEW',
      created_at: '2026-04-02T08:00:00Z',
      documents: [],
      runs: [],
      audit_events: [
        {
          id: 'aud-user-sim',
          action: 'DOCUMENT_UPLOADED',
          at: '2026-04-02T08:10:00Z',
          entity_type: 'DOCUMENT',
          actor_id: 'usr-sim-eng',
        },
        {
          id: 'aud-user-unknown',
          action: 'DOCUMENT_DELETED',
          at: '2026-04-02T08:15:00Z',
          entity_type: 'DOCUMENT',
          actor_id: null,
        },
        {
          id: 'aud-user-custom',
          action: 'DOCUMENT_UPLOADED',
          at: '2026-04-02T08:20:00Z',
          entity_type: 'DOCUMENT',
          actor_id: 'usr-finance-analyst',
        },
        {
          id: 'aud-system-event',
          action: 'VERIFICATION_RUN_COMPLETED',
          at: '2026-04-02T08:25:00Z',
          entity_type: 'VERIFICATION_RUN',
        },
      ],
      reviews: [],
    }

    const mapped = mapCaseToInvoiceRecord(rawCase)
    expect(mapped.auditHistory.length).toBe(4)

    const uploadSim = mapped.auditHistory.find((a) => a.id === 'aud-user-sim')
    expect(uploadSim?.actor).toBe('sim-engineer')
    expect(uploadSim?.title).toBe('Document Uploaded')

    const deleteUnknown = mapped.auditHistory.find((a) => a.id === 'aud-user-unknown')
    expect(deleteUnknown?.actor).toBe('Unknown actor')
    expect(deleteUnknown?.title).toBe('Document Deleted')

    const uploadCustom = mapped.auditHistory.find((a) => a.id === 'aud-user-custom')
    expect(uploadCustom?.actor).toBe('usr-finance-analyst')

    const systemEvent = mapped.auditHistory.find((a) => a.id === 'aud-system-event')
    expect(systemEvent?.actor).toBe('System')
  })

  describe('LPO status resolution (regression tests)', () => {
    const baseCase: ApiCaseDetail = {
      id: 'case-test-lpo',
      case_ref: 'VC-2026-TEST',
      project: { code: 'PRJ-1', name: 'Test Project' },
      supplier: { name: 'Test Supplier', trn: '100000000000003' },
      invoice_number_hint: 'INV-TEST',
      currency: 'AED',
      lpo_required: true,
      status: 'VERIFIED_AWAITING_REVIEW',
      created_at: '2026-04-02T08:00:00Z',
      documents: [],
      runs: [],
      audit_events: [],
      reviews: [],
    }

    it('displays Missing (Required) and never LPO Attached when LPO is required but no LPO document is attached', () => {
      const caseWithoutLpo: ApiCaseDetail = {
        ...baseCase,
        lpo_required: true,
        lpo_reason_code: 'MISSING_NOT_PROVIDED_BY_SITE',
        documents: [
          {
            id: 'doc-inv',
            doc_type: 'INVOICE',
            original_filename: 'INV-3104.pdf',
          },
          {
            id: 'doc-dn',
            doc_type: 'DELIVERY_NOTE',
            original_filename: 'DN-6200.pdf',
          },
        ],
      }
      const mapped = mapCaseToInvoiceRecord(caseWithoutLpo)
      expect(mapped.lpoRef).toBe('Missing (Required)')
      expect(mapped.lpoRef).not.toBe('LPO Attached')
    })

    it('displays LPO Attached when LPO is required and an actual LPO document exists', () => {
      const caseWithLpo: ApiCaseDetail = {
        ...baseCase,
        lpo_required: true,
        documents: [
          {
            id: 'doc-inv',
            doc_type: 'INVOICE',
            original_filename: 'INV-8821.pdf',
          },
          {
            id: 'doc-lpo',
            doc_type: 'LPO',
            original_filename: 'LPO-880.pdf',
          },
        ],
      }
      const mapped = mapCaseToInvoiceRecord(caseWithLpo)
      expect(mapped.lpoRef).toBe('LPO Attached')
    })

    it('displays correct non-required/waived state when LPO is not required', () => {
      const caseNotRequiredWithReason: ApiCaseDetail = {
        ...baseCase,
        lpo_required: false,
        lpo_reason_code: 'NOT_REQUIRED_LOW_VALUE',
        documents: [],
      }
      const mappedWithReason = mapCaseToInvoiceRecord(caseNotRequiredWithReason)
      expect(mappedWithReason.lpoRef).toBe('NOT_REQUIRED_LOW_VALUE')

      const caseNotRequiredWithoutReason: ApiCaseDetail = {
        ...baseCase,
        lpo_required: false,
        lpo_reason_code: null,
        documents: [],
      }
      const mappedWithoutReason = mapCaseToInvoiceRecord(caseNotRequiredWithoutReason)
      expect(mappedWithoutReason.lpoRef).toBe('Not Required')
    })
  })

  describe('Quantity mapping and dynamic total calculations (Step 1 Polish)', () => {
    it('correctly maps QTY_001 missing delivery note evidence (invoiced qty preserved, delivered qty 0.000)', () => {
      const rawCase: ApiCaseDetail = {
        id: 'case-test-missing-evidence',
        case_ref: 'VC-2026-MISSING',
        project: { code: 'PRJ-1', name: 'Test Project' },
        supplier: { name: 'Caelum Bulk Cement', trn: '100000000000003' },
        currency: 'AED',
        lpo_required: false,
        status: 'VERIFIED_AWAITING_REVIEW',
        created_at: '2026-04-02T08:00:00Z',
        documents: [],
        runs: [
          {
            id: 'run-missing',
            run_no: 1,
            summary: 'Missing evidence found',
            summary_labels: ['Missing evidence'],
            findings: [
              {
                id: 'fnd-qty-001',
                category: 'QTY_LINE',
                rule_code: 'QTY_001',
                outcome: 'MISSING_EVIDENCE',
                severity: 'CRITICAL',
                message: "Invoice line 'ReadyMix Concrete' has invoiced quantity 40.000 m3 but has NO matching delivery note lines linked.",
                expected: '40.000',
                actual: '0',
                unit: 'm3',
              },
            ],
          },
        ],
        audit_events: [],
        reviews: [],
      }

      const mapped = mapCaseToInvoiceRecord(rawCase)
      expect(mapped.status).toBe('Missing')
      expect(mapped.lines.length).toBe(1)
      expect(mapped.lines[0].invQty).toBe('40.000')
      expect(mapped.lines[0].dnQty).toBe('0.000')
      expect(mapped.lines[0].status).toBe('Missing')
    })

    it('correctly maps QTY_004 overbilling mismatch (invoiced 24.000, delivered 21.000, diff +3.000)', () => {
      const rawCase: ApiCaseDetail = {
        id: 'case-test-overbilling',
        case_ref: 'VC-2026-OVERBILL',
        project: { code: 'PRJ-1', name: 'Test Project' },
        supplier: { name: 'Gulf ReadyMix', trn: '100000000000003' },
        currency: 'AED',
        lpo_required: false,
        status: 'VERIFIED_AWAITING_REVIEW',
        created_at: '2026-04-02T08:00:00Z',
        documents: [],
        runs: [
          {
            id: 'run-overbill',
            run_no: 1,
            summary: 'Overbilling discrepancy found',
            summary_labels: ['Mismatch'],
            findings: [
              {
                id: 'fnd-qty-004',
                category: 'QTY_LINE',
                rule_code: 'QTY_004',
                outcome: 'MISMATCH',
                severity: 'CRITICAL',
                message: 'Invoiced quantity (24.000 m3) differs from accepted delivered quantity (21.000 m3) by +3.000 m3.',
                expected: '21.000',
                actual: '24.000',
                difference: '+3.000',
                unit: 'm3',
              },
            ],
          },
        ],
        audit_events: [],
        reviews: [],
      }

      const mapped = mapCaseToInvoiceRecord(rawCase)
      expect(mapped.status).toBe('Mismatch')
      expect(mapped.lines.length).toBe(1)
      expect(mapped.lines[0].invQty).toBe('24.000')
      expect(mapped.lines[0].dnQty).toBe('21.000')
      expect(mapped.lines[0].diff).toBe('+3.000')
    })

    it('calculates invoice totals dynamically from line items when present', () => {
      const rawCase: ApiCaseDetail = {
        id: 'case-test-dynamic-total',
        case_ref: 'VC-2026-TOTAL',
        project: { code: 'PRJ-1', name: 'Test Project' },
        supplier: { name: 'Supplier LLC', trn: '100000000000003' },
        currency: 'AED',
        lpo_required: false,
        status: 'DRAFT',
        created_at: '2026-04-02T08:00:00Z',
        documents: [],
        runs: [],
        audit_events: [],
        reviews: [],
        line_items: [
          {
            id: 'line-1',
            document_id: 'doc-inv',
            doc_type: 'INVOICE',
            line_no: 1,
            kind: 'INVOICE_LINE',
            fields: {
              description: 'Item 1',
              invoiced_qty: '10.000',
              unit: 'm3',
              unit_price: '500.00',
              line_amount: '5000.00',
            },
          },
          {
            id: 'line-2',
            document_id: 'doc-inv',
            doc_type: 'INVOICE',
            line_no: 2,
            kind: 'INVOICE_LINE',
            fields: {
              description: 'Item 2',
              invoiced_qty: '5.000',
              unit: 'm3',
              unit_price: '1000.00',
              line_amount: '5000.00',
            },
          },
        ],
      }

      const mapped = mapCaseToInvoiceRecord(rawCase)
      // 5,000 + 5,000 = 10,000.00
      expect(mapped.amountAed).toBe('10,000.00')
    })

    it('resolves synthetic pilot user IDs to human-readable names in audit history', () => {
      const rawCase: ApiCaseDetail = {
        id: 'case-test-pilot-actors',
        case_ref: 'VC-2026-PILOT',
        project: { code: 'PRJ-1', name: 'Test Project' },
        supplier: { name: 'Supplier LLC', trn: '100000000000003' },
        currency: 'AED',
        lpo_required: false,
        status: 'DRAFT',
        created_at: '2026-04-02T08:00:00Z',
        documents: [],
        runs: [],
        audit_events: [
          {
            id: 'aud-qs',
            action: 'DOCUMENT_UPLOADED',
            at: '2026-04-02T08:10:00Z',
            entity_type: 'DOCUMENT',
            actor_id: 'usr-pilot-project-qs',
          },
          {
            id: 'aud-pm',
            action: 'REVIEW_RECORDED',
            at: '2026-04-02T08:20:00Z',
            entity_type: 'REVIEW',
            actor_id: 'usr-pilot-pm-reviewer',
          },
        ],
        reviews: [],
      }

      const mapped = mapCaseToInvoiceRecord(rawCase)
      const qsEvent = mapped.auditHistory.find((a) => a.id === 'aud-qs')
      const pmEvent = mapped.auditHistory.find((a) => a.id === 'aud-pm')
      expect(qsEvent?.actor).toBe('Ramesh QS (Project QS)')
      expect(pmEvent?.actor).toBe('David PM (Commercial PM)')
    })
  })
})

