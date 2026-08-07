import shufersalLogo from '@/assets/shufersal-logo.jpg'
import ramiLevyLogo from '@/assets/rami-levy-logo.jpg'

export function SupportedRetailers() {
  return (
    <div className="mt-8 flex flex-col items-center">
      <p className="text-xs font-medium uppercase tracking-wide text-zinc-400">Supported retailers</p>
      <div className="mt-3 flex flex-wrap items-center justify-center gap-4 sm:gap-6">
        <div className="flex h-14 items-center justify-center rounded-2xl border border-zinc-200 bg-white px-6 py-3">
          <img src={shufersalLogo} alt="Shufersal" className="h-8 w-auto object-contain sm:h-9" />
        </div>
        <div className="flex h-14 items-center justify-center rounded-2xl border border-zinc-200 bg-white px-6 py-3">
          <img src={ramiLevyLogo} alt="Rami Levy" className="h-8 w-auto object-contain sm:h-9" />
        </div>
      </div>
    </div>
  )
}
