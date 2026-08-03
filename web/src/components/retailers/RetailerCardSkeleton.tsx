import { Skeleton } from '@/components/ui/skeleton'

export function RetailerCardSkeleton() {
  return (
    <div className="rounded-3xl border border-zinc-200 bg-white p-5">
      <div className="flex items-center gap-3">
        <Skeleton className="h-10 w-10 rounded-full" />
        <Skeleton className="h-5 w-28" />
      </div>
      <Skeleton className="mt-4 h-8 w-32" />
      <Skeleton className="mt-3 h-5 w-24 rounded-full" />
      <div className="mt-4 space-y-2">
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-3/4" />
        <Skeleton className="h-4 w-5/6" />
      </div>
      <Skeleton className="mt-4 h-10 w-full rounded-xl" />
    </div>
  )
}

export function RetailerComparisonSkeleton() {
  return (
    <div className="grid w-full max-w-3xl gap-4 sm:grid-cols-2">
      <RetailerCardSkeleton />
      <RetailerCardSkeleton />
    </div>
  )
}
