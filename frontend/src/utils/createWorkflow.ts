export interface CreateWorkflowState {
  isModalOpen: boolean
  isImplemented: boolean
  targetMilestone?: string
  message: string
}

export const INITIAL_CREATE_WORKFLOW_STATE: CreateWorkflowState = {
  isModalOpen: false,
  isImplemented: false,
  message:
    'New case creation is disabled in this prototype. Document upload, data persistence, verification rules evaluation, and review sign-offs run on pre-configured synthetic cases.',
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
