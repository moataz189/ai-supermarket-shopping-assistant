import { ShoppingBasket } from 'lucide-react'

export function NavBar() {
  return (
    <header className="sticky top-0 z-10 border-b border-zinc-200 bg-white/80 backdrop-blur">
      <div className="mx-auto flex max-w-5xl items-center gap-2 px-4 py-3">
        <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-600 text-white">
          <ShoppingBasket className="h-5 w-5" strokeWidth={2} />
        </span>
        <span className="text-lg font-semibold text-zinc-900">AI Supermarket Assistant</span>
      </div>
    </header>
  )
}
