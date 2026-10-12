export interface AuditEvent {
  id: string
  time: string
  title: string
  detail: string
  actor: string
  type: 'RUN' | 'LINK' | 'DN_REUSE' | 'VAT_MANUAL' | 'REVIEW' | 'SYSTEM'
  permanent?: boolean
}

export interface ComparisonLine {
  item: string
  invQty: string
  unit: string
  dnQty: string
  diff: string
  status: 'Matched' | 'Mismatch' | 'Missing' | 'Uncertain' | 'Pending' | 'Unverified'
  dnRef: string
  rejectionEvidence?: string
  ruleStatus?: string
}

export interface InvoiceRecord {
  id: string
  supplier: string
  supplierTrn: string
  invoiceNo: string
  project: string
  amountAed: string
  status: 'Matched' | 'Mismatch' | 'Missing' | 'Uncertain' | 'Pending'
  verificationStatus?: 'Matched' | 'Mismatch' | 'Missing' | 'Uncertain' | 'Ready to Verify' | 'Pending'
  reviewOutcome?: string
  date: string
  dns: string[]
  lpoRef?: string
  hasQuantityMismatch: boolean
  hasMissingEvidence: boolean
  hasUncertainEvidence: boolean
  hasUnitIncompatible: boolean
  hasDnReuse: boolean
  dnReuseDetails?: {
    otherCaseId: string
    otherCaseStatus: string
    dnNumber: string
  }
  lines: ComparisonLine[]
  auditHistory: AuditEvent[]
}

export const DEMO_INVOICES: InvoiceRecord[] = [
  {
    id: 'case-01',
    supplier: 'Caelum Bulk Cement Factory LLC (Fictional Demo)',
    supplierTrn: '100023456700003',
    invoiceNo: 'INV-8821',
    project: 'Nova Meridian Tower P1 (Fictional Demo)',
    amountAed: '45,200.00',
    status: 'Matched',
    date: '2026-03-28',
    dns: ['DN-4401', 'DN-4402'],
    lpoRef: 'LPO-2026-880',
    hasQuantityMismatch: false,
    hasMissingEvidence: false,
    hasUncertainEvidence: false,
    hasUnitIncompatible: false,
    hasDnReuse: false,
    lines: [
      {
        item: 'Ordinary Portland Cement (Bulk)',
        invQty: '40.000',
        unit: 't',
        dnQty: '40.000',
        diff: '0.000',
        status: 'Matched',
        dnRef: 'DN-4401, DN-4402',
      },
    ],
    auditHistory: [
      {
        id: 'aud-01-3',
        time: '11:20:00',
        title: 'Verification Run #1 Completed',
        detail: 'Exact match across 2 delivery notes. Zero quantity discrepancy.',
        actor: 'system',
        type: 'RUN',
      },
      {
        id: 'aud-01-2',
        time: '11:15:30',
        title: 'Delivery Notes Linked',
        detail: 'DN-4401 (20.000 t) and DN-4402 (20.000 t) reconciled to line 1.',
        actor: 'sim-qs',
        type: 'LINK',
      },
      {
        id: 'aud-01-1',
        time: '11:00:10',
        title: 'Case Initialized',
        detail: 'Synthetic case draft created with LPO attached (LPO-2026-880).',
        actor: 'sim-engineer',
        type: 'SYSTEM',
      },
    ],
  },
  {
    id: 'case-02',
    supplier: 'Zenith Matrix ReadyMix LLC (Fictional Demo)',
    supplierTrn: '100234567800003',
    invoiceNo: 'INV-9042',
    project: 'Azure Bay Marina Tower 2 (Fictional Demo)',
    amountAed: '18,750.00',
    status: 'Mismatch',
    date: '2026-03-29',
    dns: ['DN-5110', 'DN-5112'],
    lpoRef: 'LPO-2026-904',
    hasQuantityMismatch: true,
    hasMissingEvidence: false,
    hasUncertainEvidence: false,
    hasUnitIncompatible: false,
    hasDnReuse: false,
    lines: [
      {
        item: 'Concrete C30/20 Premix',
        invQty: '18.000',
        unit: 'm3',
        dnQty: '18.000',
        diff: '0.000',
        status: 'Matched',
        dnRef: 'DN-5110',
      },
      {
        item: 'Concrete C40/20 Premix',
        invQty: '24.000',
        unit: 'm3',
        dnQty: '21.000',
        diff: '+3.000',
        status: 'Mismatch',
        dnRef: 'DN-5112',
      },
    ],
    auditHistory: [
      {
        id: 'aud-02-3',
        time: '10:14:02',
        title: 'Verification Run #1 Completed',
        detail: 'Quantity discrepancy: Invoiced 24.000 m³ vs Delivered 21.000 m³ (+3.000 m³ overbilling).',
        actor: 'system',
        type: 'RUN',
      },
      {
        id: 'aud-02-2',
        time: '10:12:15',
        title: 'Delivery Notes Attached',
        detail: 'DN-5110 (18.000 m³), DN-5112 (21.000 m³) confirmed by site storekeeper.',
        actor: 'sim-engineer',
        type: 'LINK',
      },
      {
        id: 'aud-02-1',
        time: '10:10:00',
        title: 'Case Initialized',
        detail: 'Synthetic case created for Azure Bay Tower 2 concrete pour.',
        actor: 'sim-engineer',
        type: 'SYSTEM',
      },
    ],
  },
  {
    id: 'case-03',
    supplier: 'Vulcan Apex Steel Fabrication LLC (Fictional Demo)',
    supplierTrn: '100456789000003',
    invoiceNo: 'INV-3104',
    project: 'Metropolis Central Plaza (Fictional Demo)',
    amountAed: '92,400.00',
    status: 'Missing',
    date: '2026-03-30',
    dns: ['DN-6200'],
    lpoRef: undefined,
    hasQuantityMismatch: false,
    hasMissingEvidence: true,
    hasUncertainEvidence: false,
    hasUnitIncompatible: false,
    hasDnReuse: false,
    lines: [
      {
        item: 'High Tensile Deformed Steel Rebar 16mm',
        invQty: '25.000',
        unit: 't',
        dnQty: '—',
        diff: '—',
        status: 'Missing',
        dnRef: 'DN-6200 (Missing site receipt signature)',
      },
    ],
    auditHistory: [
      {
        id: 'aud-03-2',
        time: '14:22:10',
        title: 'Evidence Completeness Check Failed',
        detail: 'Required delivery note DN-6200 lacks signed site ticket. Required LPO missing without reason.',
        actor: 'system',
        type: 'RUN',
      },
      {
        id: 'aud-03-1',
        time: '14:00:00',
        title: 'Case Initialized',
        detail: 'Synthetic case registered with unverified supplier delivery note.',
        actor: 'sim-engineer',
        type: 'SYSTEM',
      },
    ],
  },
  {
    id: 'case-04',
    supplier: 'Apex Blocks & Pavers LLC',
    supplierTrn: '100567890100003',
    invoiceNo: 'INV-1290',
    project: 'Palm Crest Villa',
    amountAed: '12,300.00',
    status: 'Mismatch',
    date: '2026-03-31',
    dns: ['DN-7019'],
    lpoRef: 'LPO-2026-701',
    hasQuantityMismatch: false,
    hasMissingEvidence: false,
    hasUncertainEvidence: false,
    hasUnitIncompatible: false,
    hasDnReuse: true,
    dnReuseDetails: {
      otherCaseId: 'VC-2026-00012',
      otherCaseStatus: 'Reviewed: Verified with noted exceptions',
      dnNumber: 'DN-7019',
    },
    lines: [
      {
        item: 'Solid Concrete Blocks 200mm',
        invQty: '2,500.000',
        unit: 'pcs',
        dnQty: '2,500.000',
        diff: '0.000',
        status: 'Matched',
        dnRef: 'DN-7019',
      },
    ],
    auditHistory: [
      {
        id: 'aud-04-3',
        time: '16:05:40',
        title: 'CRITICAL: Delivery Note Reuse Detected',
        detail: 'DN-7019 is already associated with case VC-2026-00012. PERMANENT AUDIT FINDING (Rule C1).',
        actor: 'system',
        type: 'DN_REUSE',
        permanent: true,
      },
      {
        id: 'aud-04-2',
        time: '16:02:10',
        title: 'Delivery Note Uploaded',
        detail: 'DN-7019 attached. Duplicate SHA-256 and DN reference detected in global repository.',
        actor: 'sim-engineer',
        type: 'LINK',
      },
      {
        id: 'aud-04-1',
        time: '16:00:00',
        title: 'Case Initialized',
        detail: 'Synthetic case created for Palm Crest Villa masonry package.',
        actor: 'sim-engineer',
        type: 'SYSTEM',
      },
    ],
  },
  {
    id: 'case-05',
    supplier: 'Barari Aggregates LLC',
    supplierTrn: '100678901200003',
    invoiceNo: 'INV-7719',
    project: 'Alpha Horizon Tower P1',
    amountAed: '8,450.00',
    status: 'Pending',
    date: '2026-04-01',
    dns: ['DN-8812'],
    lpoRef: 'LPO-2026-770',
    hasQuantityMismatch: false,
    hasMissingEvidence: false,
    hasUncertainEvidence: false,
    hasUnitIncompatible: false,
    hasDnReuse: false,
    lines: [
      {
        item: 'Sub-base Aggregate 0-40mm',
        invQty: '120.000',
        unit: 't',
        dnQty: '120.000',
        diff: '0.000',
        status: 'Matched',
        dnRef: 'DN-8812',
      },
    ],
    auditHistory: [
      {
        id: 'aud-05-1',
        time: '09:00:00',
        title: 'Case Initialized',
        detail: 'Synthetic case awaiting initial verification run.',
        actor: 'sim-engineer',
        type: 'SYSTEM',
      },
    ],
  },
]
