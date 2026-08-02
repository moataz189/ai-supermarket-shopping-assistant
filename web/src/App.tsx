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

  async function attempt(loadingId: string, apiText: string, expectsComparison: boolean, retryDisplayText: string) {
    setTurns((prev) =>
      prev.map((t) =>
        t.id === loadingId ? { id: loadingId, role: 'assistant', status: 'loading', expectsComparison } : t,
      ),
    )
    try {
      const response = await postChat(threadId, apiText)
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
              }
            : t,
        ),
      )
    }
  }

  function sendMessage(displayText: string, apiText: string, expectsComparison: boolean) {
    const userTurn: Turn = { id: newId(), role: 'user', text: displayText }
    const loadingId = newId()
    const loadingTurn: Turn = { id: loadingId, role: 'assistant', status: 'loading', expectsComparison }
    setTurns((prev) => [...prev, userTurn, loadingTurn])
    setPhase('chat')
    void attempt(loadingId, apiText, expectsComparison, displayText)
  }

  function handleSend(text: string) {
    sendMessage(text, text, false)
  }

  function handleSelectOption(turnId: string, optionId: string, label: string) {
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
    sendMessage(label, optionId, expectsComparison)
  }

  function handleRetry(turnId: string) {
    const turn = turns.find((t) => t.id === turnId)
    if (!turn || turn.role !== 'assistant' || turn.status !== 'error') return
    void attempt(turnId, turn.retryText, false, turn.retryDisplayText)
  }

  return (
    <div className="flex min-h-screen flex-col bg-zinc-50">
      <NavBar />
      <AnimatePresence>{phase === 'hero' && <Hero onSend={handleSend} disabled={isBusy} />}</AnimatePresence>
      {phase === 'chat' && (
        <div className="flex flex-1 flex-col">
          <div className="flex-1 overflow-y-auto">
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
