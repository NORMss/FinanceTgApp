import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../api'
import ErrorNote from '../components/ErrorNote'
import PeriodPicker from '../components/PeriodPicker'
import { formatMoney } from '../format'
import type { Period } from '../types'

export default function StatsPage() {
  const [period, setPeriod] = useState<Period>('month')
  const summary = useQuery({
    queryKey: ['summary', period],
    queryFn: () => api.summary(period),
  })

  const data = summary.data

  return (
    <div className="page">
      <PeriodPicker value={period} onChange={setPeriod} />

      <ErrorNote error={summary.error} />

      <div className="card">
        <div className="totals">
          <div>
            <span>Расходы</span>
            <b>{formatMoney(data?.expense_minor ?? 0)}</b>
          </div>
          <div>
            <span>Доходы</span>
            <b>{formatMoney(data?.income_minor ?? 0)}</b>
          </div>
          <div>
            <span>Сальдо</span>
            <b style={{ color: (data?.net_minor ?? 0) < 0 ? 'var(--danger)' : 'var(--success)' }}>
              {formatMoney(data?.net_minor ?? 0, { sign: (data?.net_minor ?? 0) > 0 })}
            </b>
          </div>
        </div>
      </div>

      {data && data.by_category.length > 0 && (
        <>
          <p className="section-title">Куда ушли деньги</p>
          <div className="card card--tight">
            {data.by_category.map((item) => (
              <div className="row" key={item.category_id ?? 'none'}>
                <div className="row__icon">{item.icon || '•'}</div>
                <div className="row__body">
                  <div className="row__title">{item.name}</div>
                  {/* Полоса нагляднее процента: соотношение видно, не читая цифр */}
                  <div className="bar">
                    <i style={{ width: `${Math.max(2, Math.round(item.share * 100))}%` }} />
                  </div>
                </div>
                <div className="row__amount">
                  {formatMoney(item.amount_minor)}
                  <div className="row__sub" style={{ textAlign: 'right' }}>
                    {Math.round(item.share * 100)}%
                  </div>
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      {data && data.by_author.length > 1 && (
        <>
          <p className="section-title">Кто сколько потратил</p>
          <div className="card card--tight">
            {data.by_author.map((item) => (
              <div className="row" key={item.user_id}>
                <div className="row__icon">👤</div>
                <div className="row__body">
                  <div className="row__title">{item.name}</div>
                </div>
                <div className="row__amount">{formatMoney(item.amount_minor)}</div>
              </div>
            ))}
          </div>
        </>
      )}

      {data && data.count === 0 && (
        <p className="hint" style={{ textAlign: 'center' }}>
          За этот период данных нет
        </p>
      )}
    </div>
  )
}
