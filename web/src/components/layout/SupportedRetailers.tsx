import shufersalLogo from '@/assets/shufersal-logo.jpg'
import ramiLevyLogo from '@/assets/rami-levy-logo.jpg'

export function SupportedRetailers() {
  return (
    <div className="mt-2 flex flex-col items-center">
      <p className="text-xs font-medium uppercase tracking-wide text-zinc-400">Supported retailers</p>
      <div className="mt-1 flex flex-wrap items-center justify-center gap-2 sm:gap-3">
        <div className="flex items-center justify-center rounded-xl border border-white/60 bg-white/70 px-2.5 py-1 shadow-sm backdrop-blur-sm">
          <img src={shufersalLogo} alt="Shufersal" className="h-6 w-auto object-contain sm:h-7" />
        </div>
        <div className="flex items-center justify-center rounded-xl border border-white/60 bg-white/70 px-2.5 py-1 shadow-sm backdrop-blur-sm">
          <img src={ramiLevyLogo} alt="Rami Levy" className="h-6 w-auto object-contain sm:h-7" />
        </div>
      </div>
    </div>
  )
}
