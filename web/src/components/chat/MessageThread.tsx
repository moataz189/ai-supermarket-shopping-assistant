import { useEffect, useRef } from 'react'
import { AnimatePresence } from 'framer-motion'
import type { Turn } from '@/types'
import { UserBubble } from './UserBubble'
import { AssistantBubble } from './AssistantBubble'
import { TypingIndicator } from './TypingIndicator'
import { ClarificationCard } from '@/components/clarification/ClarificationCard'
import { RetailerComparison } from '@/components/retailers/RetailerComparison'
import { RetailerComparisonSkeleton } from '@/components/retailers/RetailerCardSkeleton'
import { RetailerCartResultView } from '@/components/RetailerCartResultView'

interface MessageThreadProps {
  turns: Turn[]
  onSelectOption: (turnId: string, optionId: string, label: string) => void
  onRetry: (turnId: string) => void
}

function leadText(status: string): string {
  return status === 'partial_success'
    ? "Here's what I found — a couple of items needed a substitution:"
    : "Here's your comparison:"
}

export function MessageThread({ turns, onSelectOption, onRetry }: MessageThreadProps) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [turns])

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 px-4 py-6">
      <AnimatePresence initial={false}>
        {turns.map((turn) => {
          if (turn.role === 'user') {
            return <UserBubble key={turn.id} text={turn.text} />
          }

          if (turn.status === 'loading') {
            return (
              <div key={turn.id} className="flex justify-start">
                {turn.expectsComparison ? <RetailerComparisonSkeleton /> : <TypingIndicator />}
              </div>
            )
          }

          if (turn.status === 'error') {
            return (
              <AssistantBubble key={turn.id}>
                <p className="text-red-700">{turn.errorMessage}</p>
                <button
                  type="button"
                  onClick={() => onRetry(turn.id)}
                  className="mt-2 text-sm font-medium text-red-700 underline underline-offset-4"
                >
                  Retry
                </button>
              </AssistantBubble>
            )
          }

          const { response, answeredOptionId } = turn
          const clarification = response.clarification

          if (clarification && clarification.reason === 'retailer_choice' && clarification.carts) {
            const carts = clarification.carts
            return (
              <div key={turn.id} className="flex justify-start">
                <RetailerComparison
                  carts={carts}
                  options={clarification.options}
                  answeredOptionId={answeredOptionId}
                  onChoose={(optionId) => {
                    const label = clarification.options.find((o) => o.id === optionId)?.label ?? optionId
                    onSelectOption(turn.id, optionId, label)
                  }}
                />
              </div>
            )
          }

          if (clarification) {
            return (
              <div key={turn.id} className="flex justify-start">
                <ClarificationCard
                  clarification={clarification}
                  answeredOptionId={answeredOptionId}
                  onSelect={(optionId) => {
                    const label = clarification.options.find((o) => o.id === optionId)?.label ?? optionId
                    onSelectOption(turn.id, optionId, label)
                  }}
                />
              </div>
            )
          }

          if (response.carts) {
            return (
              <div key={turn.id} className="flex flex-col gap-3">
                <AssistantBubble>{leadText(response.status)}</AssistantBubble>
                <div className="flex justify-start">
                  <RetailerComparison carts={response.carts} chosenRetailer={response.chosen_retailer} />
                </div>
                {response.retailer_cart_result && (
                  <div className="flex justify-start">
                    <RetailerCartResultView result={response.retailer_cart_result} />
                  </div>
                )}
                {response.warnings.length > 0 && (
                  <AssistantBubble>
                    <ul className="list-disc space-y-1 pl-4 text-sm">
                      {response.warnings.map((w, i) => (
                        <li key={i}>{JSON.stringify(w)}</li>
                      ))}
                    </ul>
                  </AssistantBubble>
                )}
              </div>
            )
          }

          return <AssistantBubble key={turn.id}>All done.</AssistantBubble>
        })}
      </AnimatePresence>
      <div ref={bottomRef} />
    </div>
  )
}
