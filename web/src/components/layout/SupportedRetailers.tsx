import shufersalLogo from '@/assets/shufersal-logo.jpg'
import ramiLevyLogo from '@/assets/rami-levy-logo.jpg'

export function SupportedRetailers() {
  return (
    <div className="mt-6 flex flex-col items-center">
      <p className="text-xs font-medium uppercase tracking-wide text-zinc-400">Supported retailers</p>
      <div className="mt-2 flex flex-wrap items-center justify-center gap-3 sm:gap-4">
        <div className="flex items-center justify-center rounded-2xl border border-zinc-200 bg-white px-4 py-2.5">
          <img src={shufersalLogo} alt="Shufersal" className="h-11 w-auto object-contain sm:h-12" />
        </div>
        <div className="flex items-center justify-center rounded-2xl border border-zinc-200 bg-white px-4 py-2.5">
          <img src={ramiLevyLogo} alt="Rami Levy" className="h-11 w-auto object-contain sm:h-12" />
        </div>
      </div>
    </div>
  )
}
