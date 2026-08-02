import { useState } from 'react'
import type { ChatResponse } from './api'
import { postChat } from './api'
import { ClarificationPrompt } from './components/ClarificationPrompt'
import { RetailerCartsView } from './components/RetailerCartsView'
import './App.css'

function App() {
  const [message, setMessage] = useState('')
  const [threadId, setThreadId] = useState<string | null>(null)
  const [result, setResult] = useState<ChatResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function send(text: string) {
    setLoading(true)
    setError(null)
    try {
      const response = await postChat(threadId, text)
      setThreadId(response.thread_id)
      setResult(response)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong')
    } finally {
      setLoading(false)
    }
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!message.trim()) return
    void send(message)
    setMessage('')
  }

  function handleRestart() {
    setThreadId(null)
    setResult(null)
    setMessage('')
    setError(null)
  }

  return (
    <div className="app">
      <h1>AI Supermarket Shopping Assistant</h1>

      {!result && (
        <form onSubmit={handleSubmit} className="chat-form">
          <input
            type="text"
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder="e.g. milk, bread, and eggs, budget 100"
            disabled={loading}
          />
          <button type="submit" disabled={loading || !message.trim()}>
            Send
          </button>
        </form>
      )}

      {loading && <p>Working on it…</p>}
      {error && <p className="error">{error}</p>}

      {result?.status === 'needs_clarification' && result.clarification && (
        <ClarificationPrompt
          clarification={result.clarification}
          onSelect={(optionId) => void send(optionId)}
        />
      )}

      {result?.status === 'awaiting_retailer_choice' && result.clarification?.carts && (
        <RetailerCartsView
          carts={result.clarification.carts}
          onChoose={(choice) => void send(choice)}
        />
      )}

      {result && !['needs_clarification', 'awaiting_retailer_choice'].includes(result.status) && (
        <div className="final-result">
          {result.carts && (
            <RetailerCartsView carts={result.carts} chosenRetailer={result.chosen_retailer} />
          )}
          {result.warnings.length > 0 && (
            <ul className="warnings">
              {result.warnings.map((w, i) => (
                <li key={i}>{JSON.stringify(w)}</li>
              ))}
            </ul>
          )}
          <button type="button" onClick={handleRestart}>
            Start a new request
          </button>
        </div>
      )}
    </div>
  )
}

export default App
