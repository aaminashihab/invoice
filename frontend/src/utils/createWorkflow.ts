/**
 * Utilities and validation logic for Case Creation & Manual Data Entry Workflow (M4C Step 4).
 */

export interface CreateWorkflowState {
  isModalOpen: boolean
  isImplemented: boolean
  targetMilestone?: string
  message: string
}

export const INITIAL_CREATE_WORKFLOW_STATE: CreateWorkflowState = {
  isModalOpen: false,
  isImplemented: true,
  message:
    'Create and populate a verification case with synthetic commercial evidence. Enforces canonical role authorization (QS/ADMIN) and segregation of duties.',
}

export function openCreateWorkflow(current: CreateWorkflowState): CreateWorkflowState {
  return {
    ...current,
    isModalOpen: true,
  }
}

export function closeCreateWorkflow(current: CreateWorkflowState): CreateWorkflowState {
  return {
    ...current,
    isModalOpen: false,
  }
}

/**
 * Enforce canonical role authorization for case creation (D6 & Segregation of Duties).
 * Only Quantity Surveyors (QS) and Administrators may initiate verification cases.
 */
export function canCreateCase(role?: string | null): boolean {
  if (!role) return false
  const normalized = role.toUpperCase()
  return normalized === 'QS' || normalized === 'ADMIN'
}

/**
 * Validate that a string represents a valid Decimal number.
 */
export function validateDecimal(val: string, mustBePositive = true): boolean {
  if (!val || typeof val !== 'string') return false
  const trimmed = val.trim()
  if (!trimmed) return false
  const num = Number(trimmed)
  if (isNaN(num)) return false
  if (mustBePositive) {
    return num > 0
  }
  return num >= 0
}

/**
 * Validate case reference format.
 */
export function validateCaseRef(ref: string): string | null {
  if (!ref || !ref.trim()) {
    return 'Case reference is required.'
  }
  const trimmed = ref.trim()
  if (trimmed.length < 3) {
    return 'Case reference must be at least 3 characters long.'
  }
  if (!/^[A-Za-z0-9_-]+$/.test(trimmed)) {
    return 'Case reference must contain only letters, numbers, hyphens, and underscores.'
  }
  return null
}
