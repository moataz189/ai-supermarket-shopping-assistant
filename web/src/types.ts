import type { ChatResponse } from './api'

export type Turn =
  | { id: string; role: 'user'; text: string }
  | { id: string; role: 'assistant'; status: 'loading'; expectsComparison: boolean }
  | {
      id: string
      role: 'assistant'
      status: 'done'
      response: ChatResponse
      answeredOptionId?: string
    }
  | {
      id: string
      role: 'assistant'
      status: 'error'
      errorMessage: string
      retryText: string
      retryDisplayText: string
    }

export type Phase = 'hero' | 'chat'
