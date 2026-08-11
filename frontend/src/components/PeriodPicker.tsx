import { PERIOD_LABELS } from '../format'
import { haptic } from '../telegram'
import type { Period } from '../types'

const PERIODS: Period[] = ['week', 'month', 'prev_month', 'year']

export default function PeriodPicker({
  value,
  onChange,
}: {
  value: Period
  onChange: (period: Period) => void
}) {
  return (
    <div className="segmented">
      {PERIODS.map((period) => (
        <button
          key={period}
          type="button"
          data-active={value === period}
          onClick={() => {
            haptic()
            onChange(period)
          }}
        >
          {PERIOD_LABELS[period]}
        </button>
      ))}
    </div>
  )
}
