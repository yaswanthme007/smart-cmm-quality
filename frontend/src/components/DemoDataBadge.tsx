/** Honesty rule (Section 1.3): synthetic data is always labelled on screen. */
export function DemoDataBadge() {
  return (
    <span
      className="rounded-full border border-amber-300 bg-amber-50 px-3 py-1 text-sm font-medium text-amber-800"
      title="All data shown is synthetic demo data, not real plant data"
    >
      Demo data
    </span>
  )
}
