import { formatMoney, percentDelta } from '../format'
import { formatRange, progress } from '../period'
import type { Summary } from '../types'

interface Props {
  data: Summary
  onResetExclusions: () => void
}

/**
 * Три цифры отчёта и всё, что нужно, чтобы им верить.
 *
 * Подпись периода берётся из ответа сервера, а не из выбранной кнопки: пресет
 * превращается в конкретные даты на сервере, и заголовок обязан описывать те
 * деньги, что показаны, а не те, что просили.
 */
export default function ReportTotals({ data, onResetExclusions }: Props) {
  const { days, passed } = progress(data.period_start, data.period_end)
  const perDay = Math.round(data.expense_minor / passed)
  // Прогноз имеет смысл только внутри незакончившегося периода: у прошлого месяца
  // «при таком темпе выйдет» — это уже не прогноз, а та же сумма другими словами
  const running = passed < days
  const forecast = running ? perDay * days : 0

  const delta = data.previous ? percentDelta(data.expense_minor, data.previous.expense_minor) : null

  return (
    <div className="card">
      <div className="totals">
        <div>
          <span>Расходы</span>
          <b>{formatMoney(data.expense_minor)}</b>
        </div>
        <div>
          <span>Доходы</span>
          <b>{formatMoney(data.income_minor)}</b>
        </div>
        <div>
          <span>Сальдо</span>
          <b style={{ color: data.net_minor < 0 ? 'var(--danger)' : 'var(--success)' }}>
            {formatMoney(data.net_minor, { sign: data.net_minor > 0 })}
          </b>
        </div>
      </div>

      <div className="totals__meta">
        <span>{formatRange(data.period_start, data.period_end)}</span>
        {data.expense_minor > 0 && <span>{formatMoney(perDay)} в день</span>}
        {delta && (
          <span data-tone={data.expense_minor > (data.previous?.expense_minor ?? 0) ? 'up' : 'down'}>
            {delta} к прошлому
          </span>
        )}
      </div>

      {/* Скрытое рядом с итогом — условие доверия к цифре слева. Без него непонятно,
          месяц был дешёвый или из него что-то вычли */}
      {data.excluded_minor > 0 && (
        <p className="hint totals__excluded">
          Скрыто {formatMoney(data.excluded_minor)} по исключениям{' '}
          <button className="btn btn--link" type="button" onClick={onResetExclusions}>
            показать всё
          </button>
        </p>
      )}

      {running && forecast > 0 && (
        <p className="hint" style={{ margin: '6px 0 0' }}>
          При таком темпе за период выйдет {formatMoney(forecast)}
        </p>
      )}
    </div>
  )
}
