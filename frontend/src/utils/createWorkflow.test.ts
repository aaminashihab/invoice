import { describe, it, expect } from 'vitest'
import {
  INITIAL_CREATE_WORKFLOW_STATE,
  openCreateWorkflow,
  closeCreateWorkflow,
  canCreateCase,
  validateDecimal,
  validateCaseRef,
} from './createWorkflow'

describe('Create Workflow Behavior (M4C Step 4)', () => {
  it('initializes with implemented state enabled for authorized roles', () => {
    expect(INITIAL_CREATE_WORKFLOW_STATE.isImplemented).toBe(true)
    expect(INITIAL_CREATE_WORKFLOW_STATE.isModalOpen).toBe(false)
    expect(INITIAL_CREATE_WORKFLOW_STATE.message).toContain('QS/ADMIN')
  })

  it('opens and closes the workflow creation modal correctly', () => {
    const opened = openCreateWorkflow(INITIAL_CREATE_WORKFLOW_STATE)
    expect(opened.isModalOpen).toBe(true)

    const closed = closeCreateWorkflow(opened)
    expect(closed.isModalOpen).toBe(false)
  })

  it('enforces canonical role permissions: QS and ADMIN allowed, REVIEWER and ENGINEER denied', () => {
    expect(canCreateCase('QS')).toBe(true)
    expect(canCreateCase('ADMIN')).toBe(true)
    expect(canCreateCase('qs')).toBe(true)
    expect(canCreateCase('admin')).toBe(true)

    expect(canCreateCase('REVIEWER')).toBe(false)
    expect(canCreateCase('ENGINEER')).toBe(false)
    expect(canCreateCase('ACCOUNTS')).toBe(false)
    expect(canCreateCase(null)).toBe(false)
    expect(canCreateCase(undefined)).toBe(false)
  })

  it('validates exact Decimal numeric inputs strictly', () => {
    expect(validateDecimal('36.00', true)).toBe(true)
    expect(validateDecimal('0.001', true)).toBe(true)
    expect(validateDecimal('0', true)).toBe(false) // Must be positive
    expect(validateDecimal('0', false)).toBe(true) // Non-negative
    expect(validateDecimal('-5.00', false)).toBe(false)
    expect(validateDecimal('abc')).toBe(false)
    expect(validateDecimal('')).toBe(false)
    expect(validateDecimal('   ')).toBe(false)
  })

  it('validates case reference naming format', () => {
    expect(validateCaseRef('CASE-2026-SYN-06')).toBeNull()
    expect(validateCaseRef('CASE_01')).toBeNull()
    expect(validateCaseRef('')).toBe('Case reference is required.')
    expect(validateCaseRef('C1')).toBe('Case reference must be at least 3 characters long.')
    expect(validateCaseRef('CASE 01!')).toBe('Case reference must contain only letters, numbers, hyphens, and underscores.')
  })
})
