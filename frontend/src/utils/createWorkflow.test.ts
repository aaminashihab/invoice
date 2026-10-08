import { describe, it, expect } from 'vitest'
import {
  INITIAL_CREATE_WORKFLOW_STATE,
  openCreateWorkflow,
  closeCreateWorkflow,
} from './createWorkflow'

describe('Create Workflow Behavior (Prototype Boundaries)', () => {
  it('initializes in disabled state with clear boundary messaging', () => {
    expect(INITIAL_CREATE_WORKFLOW_STATE.isImplemented).toBe(false)
    expect(INITIAL_CREATE_WORKFLOW_STATE.isModalOpen).toBe(false)
    expect(INITIAL_CREATE_WORKFLOW_STATE.message).toContain('New case creation is disabled')
  })

  it('opens and closes the workflow placeholder modal without pretending creation succeeded', () => {
    const opened = openCreateWorkflow(INITIAL_CREATE_WORKFLOW_STATE)
    expect(opened.isModalOpen).toBe(true)
    expect(opened.isImplemented).toBe(false)

    const closed = closeCreateWorkflow(opened)
    expect(closed.isModalOpen).toBe(false)
  })
})
