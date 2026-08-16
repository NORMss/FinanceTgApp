import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { api } from '../api'
import ErrorNote from '../components/ErrorNote'
import { formatMoney } from '../format'
import { getTimezone, notify } from '../telegram'
import type { User } from '../types'

const TIME_PATTERN = /^\d{2}:\d{2}$/

interface Props {
  currentUser: User
  onDone: (message: string) => void
  onOpenCategories: () => void
}

export default function MorePage({ currentUser, onDone, onOpenCategories }: Props) {
  const queryClient = useQueryClient()
  const balances = useQuery({ queryKey: ['balances'], queryFn: api.balances })
  const settle = useQuery({ queryKey: ['settle'], queryFn: api.settle })
  const sync = useQuery({ queryKey: ['sync-status'], queryFn: api.syncStatus })

  const reminder = useQuery({ queryKey: ['reminder'], queryFn: api.reminder })

  // Поле времени редактируется локально: пока человек крутит часы в системном
  // выборе, промежуточные значения на сервер отправлять незачем
  const [time, setTime] = useState('')
  useEffect(() => {
    if (reminder.data) setTime(reminder.data.time)
  }, [reminder.data])

  const saveReminder = useMutation({
    mutationFn: api.saveReminder,
    onSuccess: (result) => {
      notify('success')
      queryClient.setQueryData(['reminder'], result)
      onDone(
        result.enabled ? `Напомню в ${result.time}` : 'Напоминания выключены',
      )
    },
    onError: (error) => {
      notify('error')
      onDone((error as Error).message)
    },
  })

  /** Отправляем время, только когда оно дособрано и отличается от сохранённого. */
  const commitTime = (value: string) => {
    if (!TIME_PATTERN.test(value) || value === reminder.data?.time) return
    saveReminder.mutate({ time: value, tz: getTimezone() })
  }

  const push = useMutation({
    mutationFn: api.syncPush,
    onSuccess: (result) => {
      notify('success')
      onDone(`Выгружено: ${result.updated + result.appended} строк`)
      queryClient.invalidateQueries({ queryKey: ['sync-status'] })
    },
    onError: (error) => onDone((error as Error).message),
  })

  const pull = useMutation({
    mutationFn: api.syncPull,
    onSuccess: (result) => {
      notify('success')
      onDone(`Принято правок: ${result.applied}, новых: ${result.created}`)
      queryClient.invalidateQueries()
    },
    onError: (error) => onDone((error as Error).message),
  })

  return (
    <div className="page">
      <ErrorNote error={balances.error ?? settle.error ?? sync.error ?? reminder.error} />

      <button className="btn btn--ghost" type="button" onClick={onOpenCategories}>
        🗂 Категории и подкатегории
      </button>

      <p className="section-title">Напоминание</p>
      <div className="card card--tight">
        <div className="row">
          <div className="row__icon">🔔</div>
          <div className="row__body">
            <div className="row__title">Напоминать о тратах</div>
            <div className="row__sub">
              Бот напишет вечером, если за день ничего не записано
            </div>
          </div>
          <label className="switch">
            <input
              type="checkbox"
              checked={reminder.data?.enabled ?? false}
              disabled={!reminder.data || saveReminder.isPending}
              onChange={(event) =>
                saveReminder.mutate({ enabled: event.target.checked, tz: getTimezone() })
              }
              aria-label="Напоминать о тратах"
            />
            <span />
          </label>
        </div>

        {reminder.data?.enabled && (
          <div className="row">
            <div className="row__body">
              <div className="row__title">Время</div>
              <div className="row__sub">по вашему поясу · {reminder.data.tz}</div>
            </div>
            <input
              className="field field--time"
              type="time"
              value={time}
              onChange={(event) => {
                setTime(event.target.value)
                commitTime(event.target.value)
              }}
              onBlur={() => commitTime(time)}
              aria-label="Время напоминания"
            />
          </div>
        )}
      </div>
      {reminder.data && !reminder.data.delivery_ready && (
        <p className="hint">
          Бот сейчас выключен, поэтому напоминания не приходят. Настройка сохранится
          и заработает, как только он запустится.
        </p>
      )}

      <p className="section-title">Остатки</p>
      <div className="card card--tight">
        {(balances.data?.accounts ?? []).map((account) => (
          <div className="row" key={account.account_id}>
            <div className="row__icon">{account.is_shared ? '👥' : '👤'}</div>
            <div className="row__body">
              <div className="row__title">{account.name}</div>
              <div className="row__sub">{account.currency}</div>
            </div>
            <div
              className="row__amount"
              style={{ color: account.balance_minor < 0 ? 'var(--danger)' : undefined }}
            >
              {formatMoney(account.balance_minor)}
            </div>
          </div>
        ))}
        {balances.data && (
          <div className="row">
            <div className="row__body">
              <div className="row__title">
                <b>Всего</b>
              </div>
            </div>
            <div className="row__amount">
              <b>{formatMoney(balances.data.total_minor)}</b>
            </div>
          </div>
        )}
      </div>

      <p className="section-title">Взаиморасчёты</p>
      <div className="card">
        <p style={{ margin: '0 0 8px' }}>{settle.data?.hint ?? '…'}</p>
        {(settle.data?.users ?? []).map((user) => (
          <div className="row" key={user.user_id}>
            <div className="row__body">
              <div className="row__title">
                {user.name}
                {user.user_id === currentUser.id ? ' (вы)' : ''}
              </div>
              <div className="row__sub">
                заплатил {formatMoney(user.paid_minor)} · доля {formatMoney(user.owed_minor)}
              </div>
            </div>
            <div
              className="row__amount"
              style={{ color: user.net_minor < 0 ? 'var(--danger)' : 'var(--success)' }}
            >
              {formatMoney(user.net_minor, { sign: user.net_minor > 0 })}
            </div>
          </div>
        ))}
      </div>

      <p className="section-title">Google Sheets</p>
      <div className="card">
        {sync.data?.configured ? (
          <>
            <p className="hint" style={{ marginTop: 0 }}>
              В очереди на выгрузку: {sync.data.pending}
              {sync.data.last_push_at
                ? ` · последняя выгрузка ${new Date(sync.data.last_push_at).toLocaleString('ru')}`
                : ''}
            </p>
            {sync.data.last_error && <p className="error">{sync.data.last_error}</p>}
            <div style={{ display: 'flex', gap: 8 }}>
              <button
                className="btn btn--ghost"
                type="button"
                disabled={push.isPending}
                onClick={() => push.mutate()}
              >
                Выгрузить
              </button>
              <button
                className="btn btn--ghost"
                type="button"
                disabled={pull.isPending}
                onClick={() => pull.mutate()}
              >
                Забрать правки
              </button>
            </div>
            {sync.data.spreadsheet_url && (
              <p style={{ marginBottom: 0 }}>
                <a href={sync.data.spreadsheet_url} target="_blank" rel="noreferrer">
                  Открыть таблицу
                </a>
              </p>
            )}
          </>
        ) : (
          <p className="hint" style={{ margin: 0 }}>
            Синхронизация не настроена. Добавьте ID таблицы и ключ сервис-аккаунта в .env —
            приложение работает и без неё.
          </p>
        )}
      </div>

      <p className="hint" style={{ textAlign: 'center' }}>
        Вы вошли как {currentUser.display_name}
      </p>
    </div>
  )
}
