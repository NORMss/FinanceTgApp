import { useState } from 'react'

import { formatMoney } from '../format'
import { haptic } from '../telegram'
import type { Trend } from '../types'

const MONTHS_SHORT = [
  'янв', 'фев', 'мар', 'апр', 'май', 'июн',
  'июл', 'авг', 'сен', 'окт', 'ноя', 'дек',
]

/** «2026-08» -> «авг». Год подписываем только в январе — иначе подписи не помещаются. */
function monthLabel(key: string): string {
  const [year, month] = key.split('-')
  const short = MONTHS_SHORT[Number(month) - 1] ?? month
  return month === '01' ? `${short} ${year.slice(2)}` : short
}

interface Props {
  trend: Trend
}

/**
 * Помесячные столбики расходов.
 *
 * Рисуется своим SVG: в проекте нет ни одной графической зависимости, и тащить
 * сюда библиотеку ради десятка прямоугольников значит удвоить вес приложения,
 * которое открывают по мобильной сети внутри Telegram.
 *
 * Столбики, а не линия: месяцев мало, промежуточных значений между ними не бывает,
 * и линия соединяла бы точки, между которыми ничего нет.
 */
export default function TrendChart({ trend }: Props) {
  const [picked, setPicked] = useState<string | null>(null)

  const category = trend.categories.find((item) => item.category_id === picked)
  const values = category ? category.amounts : trend.expense
  const peak = Math.max(1, ...values)

  if (trend.months.length < 2) {
    return (
      <p className="hint" style={{ textAlign: 'center' }}>
        Для сравнения нужно хотя бы два месяца — выберите период пошире
      </p>
    )
  }

  const select = (id: string | null) => {
    haptic()
    setPicked(id)
  }

  return (
    <>
      <div className="card">
        <div className="chart" role="img" aria-label="Расходы по месяцам">
          {trend.months.map((month, index) => {
            const value = values[index] ?? 0
            const height = Math.max(2, Math.round((value / peak) * 100))
            const last = index === trend.months.length - 1
            return (
              <div className="chart__col" key={month}>
                {/* Подпись суммы только у самого высокого и у последнего столбика:
                    двенадцать чисел подряд на экране телефона нечитаемы */}
                <span className="chart__value">
                  {value === peak || last ? formatMoney(value) : ''}
                </span>
                <i style={{ height: `${height}%` }} data-last={last} />
                <span className="chart__label">{monthLabel(month)}</span>
              </div>
            )
          })}
        </div>
      </div>

      <div className="chips">
        <button
          type="button"
          className="chip"
          data-active={picked === null}
          onClick={() => select(null)}
        >
          Все расходы
        </button>
        {trend.categories.map((item) => (
          <button
            key={item.category_id ?? 'none'}
            type="button"
            className="chip"
            data-active={picked === item.category_id}
            onClick={() => select(item.category_id)}
          >
            {item.icon} {item.name}
          </button>
        ))}
      </div>
    </>
  )
}
