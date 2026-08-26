import { useState } from 'react'

import { PERIOD_LABELS } from '../format'
import { type Range, monthAnchor, shiftAnchor } from '../period'
import { haptic } from '../telegram'
import type { Period } from '../types'

const PRESETS: Period[] = ['week', 'month', 'prev_month', 'year']
/** Реже нужные, но уже поддержанные сервером — прячем в шторку, а не выкидываем. */
const EXTRA: Period[] = ['30d', 'all']

interface Props {
  value: Range
  onChange: (range: Range) => void
  /** Подпись, посчитанная сервером по фактическим границам периода. */
  label?: string
}

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

/**
 * Период отчёта: четыре кнопки на каждый день и шторка на всё остальное.
 *
 * Кнопок именно четыре: пятая не помещается на экран телефона, а «30 дней» и «Всё
 * время» спрашивают заметно реже, чем неделю и месяц. Стрелки листания появляются,
 * когда выбран конкретный месяц, — сравнить март с апрелем двумя касаниями быстрее,
 * чем дважды открыть календарь.
 */
export default function PeriodPicker({ value, onChange, label }: Props) {
  const [open, setOpen] = useState(false)
  const [from, setFrom] = useState(today())
  const [to, setTo] = useState(today())

  const pick = (range: Range) => {
    haptic()
    onChange(range)
    setOpen(false)
  }

  const activePreset = value.kind === 'preset' ? value.preset : null
  const anchor = value.kind === 'month' ? value.anchor : monthAnchor()

  return (
    <>
      <div className="segmented">
        {PRESETS.map((period) => (
          <button
            key={period}
            type="button"
            data-active={activePreset === period}
            onClick={() => pick({ kind: 'preset', preset: period })}
          >
            {PERIOD_LABELS[period]}
          </button>
        ))}
        <button
          type="button"
          data-active={value.kind !== 'preset'}
          title="Выбрать период"
          aria-label="Выбрать период"
          onClick={() => {
            haptic()
            setOpen(true)
          }}
        >
          ⋯
        </button>
      </div>

      {/* Стрелки листания. Показываем только для конкретного месяца: у пресета
          «Неделя» соседний месяц не имеет смысла, а у «Всего времени» соседей нет */}
      {value.kind === 'month' && (
        <div className="stepper">
          <button
            type="button"
            className="icon-btn"
            aria-label="Предыдущий месяц"
            onClick={() => pick({ kind: 'month', anchor: shiftAnchor(anchor, -1) })}
          >
            ‹
          </button>
          <b>{label ?? anchor}</b>
          <button
            type="button"
            className="icon-btn"
            aria-label="Следующий месяц"
            disabled={anchor >= monthAnchor()}
            onClick={() => pick({ kind: 'month', anchor: shiftAnchor(anchor, 1) })}
          >
            ›
          </button>
        </div>
      )}

      {open && (
        <div className="sheet-backdrop" onClick={() => setOpen(false)} role="presentation">
          <div className="sheet" onClick={(event) => event.stopPropagation()} role="dialog">
            <div className="sheet__grip" />

            <p className="section-title" style={{ margin: 0 }}>
              Период
            </p>

            <div className="chips">
              {EXTRA.map((period) => (
                <button
                  key={period}
                  type="button"
                  className="chip"
                  data-active={activePreset === period}
                  onClick={() => pick({ kind: 'preset', preset: period })}
                >
                  {PERIOD_LABELS[period]}
                </button>
              ))}
              <button
                type="button"
                className="chip"
                data-active={value.kind === 'month'}
                onClick={() => pick({ kind: 'month', anchor: monthAnchor() })}
              >
                Листать месяцы
              </button>
            </div>

            <p className="section-title" style={{ marginBottom: 0 }}>
              Свой диапазон
            </p>
            <div className="icon-row">
              <input
                className="field"
                type="date"
                value={from}
                max={to}
                onChange={(event) => setFrom(event.target.value)}
                aria-label="Начало периода"
              />
              <input
                className="field"
                type="date"
                value={to}
                min={from}
                onChange={(event) => setTo(event.target.value)}
                aria-label="Конец периода"
              />
            </div>

            <div className="sheet__actions">
              <button className="btn btn--ghost" type="button" onClick={() => setOpen(false)}>
                Отмена
              </button>
              <button
                className="btn"
                type="button"
                disabled={!from || !to || from > to}
                onClick={() => pick({ kind: 'custom', from, to })}
              >
                Показать
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
