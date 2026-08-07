import { useState } from 'react'
import { AnimatePresence } from 'framer-motion'
import { NavBar } from '@/components/layout/NavBar'
import { Hero } from '@/components/layout/Hero'
import { MessageThread } from '@/components/chat/MessageThread'
import { ChatInput } from '@/components/chat/ChatInput'
import { postChat } from '@/api'
import type { Phase, Turn } from '@/types'

function newId() {
  return crypto.randomUUID()
}

function App() {
  const [phase, setPhase] = useState<Phase>('hero')
  const [threadId, setThreadId] = useState<string | null>(null)
  const [turns, setTurns] = useState<Turn[]>([])

  const isBusy = turns.some((t) => t.role === 'assistant' && t.status === 'loading')

  async function attempt(
    loadingId: string,
    apiText: string,
    expectsComparison: boolean,
    retryDisplayText: string,
    requestThreadId: string | null,
  ) {
    setTurns((prev) =>
      prev.map((t) =>
        t.id === loadingId ? { id: loadingId, role: 'assistant', status: 'loading', expectsComparison } : t,
      ),
    )
    try {
      const response = await postChat(requestThreadId, apiText)
      setThreadId(response.thread_id)
      setTurns((prev) =>
        prev.map((t) => (t.id === loadingId ? { id: loadingId, role: 'assistant', status: 'done', response } : t)),
      )
    } catch (e) {
      const errorMessage = e instanceof Error ? e.message : 'Something went wrong'
      setTurns((prev) =>
        prev.map((t) =>
          t.id === loadingId
            ? {
                id: loadingId,
                role: 'assistant',
                status: 'error',
                errorMessage,
                retryText: apiText,
                retryDisplayText,
                requestThreadId,
              }
            : t,
        ),
      )
    }
  }

  function isAwaitingAnswer(): boolean {
    const lastDone = [...turns].reverse().find((t) => t.role === 'assistant' && t.status === 'done')
    return Boolean(lastDone && lastDone.role === 'assistant' && lastDone.status === 'done' && lastDone.response.clarification)
  }

  function sendMessage(
    displayText: string,
    apiText: string,
    expectsComparison: boolean,
    requestThreadId: string | null,
  ) {
    const userTurn: Turn = { id: newId(), role: 'user', text: displayText }
    const loadingId = newId()
    const loadingTurn: Turn = { id: loadingId, role: 'assistant', status: 'loading', expectsComparison }
    setTurns((prev) => [...prev, userTurn, loadingTurn])
    setPhase('chat')
    void attempt(loadingId, apiText, expectsComparison, displayText, requestThreadId)
  }

  function handleSend(text: string) {
    const requestThreadId = isAwaitingAnswer() ? threadId : null
    sendMessage(text, text, false, requestThreadId)
  }

  function handleSelectOption(turnId: string, optionId: string, label: string) {
    if (isBusy) return
    const turn = turns.find((t) => t.id === turnId)
    const expectsComparison =
      turn?.role === 'assistant' && turn.status === 'done'
        ? turn.response.clarification?.reason === 'retailer_choice'
        : false

    setTurns((prev) =>
      prev.map((t) =>
        t.id === turnId && t.role === 'assistant' && t.status === 'done' ? { ...t, answeredOptionId: optionId } : t,
      ),
    )
    sendMessage(label, optionId, expectsComparison, threadId)
  }

  function handleRetry(turnId: string) {
    if (isBusy) return
    const turn = turns.find((t) => t.id === turnId)
    if (!turn || turn.role !== 'assistant' || turn.status !== 'error') return
    void attempt(turnId, turn.retryText, false, turn.retryDisplayText, turn.requestThreadId)
  }

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-zinc-50">
      <NavBar />
      {phase === 'hero' && (
        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
          <AnimatePresence>
            <Hero onSend={handleSend} disabled={isBusy} />
          </AnimatePresence>
        </div>
      )}
      {phase === 'chat' && (
        <div className="flex min-h-0 flex-1 flex-col">
          <div className="min-h-0 flex-1 overflow-y-auto">
            <MessageThread turns={turns} onSelectOption={handleSelectOption} onRetry={handleRetry} />
          </div>
          <div className="sticky bottom-0 border-t border-zinc-200 bg-zinc-50/95 px-4 py-4 backdrop-blur">
            <ChatInput variant="bar" onSend={handleSend} disabled={isBusy} />
          </div>
        </div>
      )}
    </div>
  )
}

export default App
