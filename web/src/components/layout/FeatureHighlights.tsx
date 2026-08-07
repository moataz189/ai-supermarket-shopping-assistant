const FEATURES = [
  {
    emoji: '🛒',
    title: 'Smart Shopping Lists',
    description: 'Create grocery carts from natural language.',
  },
  {
    emoji: '🍳',
    title: 'Recipe-Based Shopping',
    description: 'Turn recipes into complete shopping carts.',
  },
  {
    emoji: '💰',
    title: 'Budget Comparison',
    description: 'Compare Shufersal and Rami Levy and recommend the best option.',
  },
]

export function FeatureHighlights() {
  return (
    <div className="mt-10 grid w-full grid-cols-1 gap-6 sm:grid-cols-3 sm:gap-6">
      {FEATURES.map(({ emoji, title, description }) => (
        <div key={title} className="flex flex-col items-center gap-1 text-center">
          <span className="text-2xl" aria-hidden>
            {emoji}
          </span>
          <p className="text-sm font-semibold text-zinc-700">{title}</p>
          <p className="text-sm text-zinc-500">{description}</p>
        </div>
      ))}
    </div>
  )
}
