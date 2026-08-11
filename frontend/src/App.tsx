import { useQuery } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiError, login } from './api'
import AddPage from './pages/AddPage'
import HistoryPage from './pages/HistoryPage'
import MorePage from './pages/MorePage'
import StatsPage from './pages/StatsPage'
import { isStandalone } from './telegram'

type Tab = 'add' | 'history' | 'stats' | 'more'

const TABS: { id: Tab; icon: string; label: string }[] = [
  { id: 'add', icon: '➕', label: 'Добавить' },
  { id: 'history', icon: '📜', label: 'История' },
  { id: 'stats', icon: '📊', label: 'Отчёт' },
  { id: 'more', icon: '⚙️', label: 'Ещё' },
]

export default function App() {
  const [tab, setTab] = useState<Tab>('add')
  const [toast, setToast] = useState<string | null>(null)
  const toastTimer = useRef<number>()

  const showToast = useCallback((message: string) => {
    setToast(message)
    window.clearTimeout(toastTimer.current)
    toastTimer.current = window.setTimeout(() => setToast(null), 2200)
  }, [])

  useEffect(() => () => window.clearTimeout(toastTimer.current), [])

  const session = useQuery({
    queryKey: ['session'],
    queryFn: login,
    staleTime: Infinity,
    retry: false,
  })

  if (session.isPending) {
    return <div className="center">Загружаем…</div>
  }

  if (session.isError) {
    const error = session.error
    const forbidden = error instanceof ApiError && error.status === 403
    return (
      <div className="center">
        <div>
          <p className="error">
            {forbidden
              ? 'Доступ к этому приложению не открыт для вашего аккаунта.'
              : 'Не получилось войти.'}
          </p>
          {isStandalone && (
            <p className="hint">
              Приложение открыто вне Telegram. Запустите его кнопкой в боте — вход работает
              через Telegram.
            </p>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="app">
      {tab === 'add' && <AddPage onDone={showToast} />}
      {tab === 'history' && <HistoryPage onDone={showToast} />}
      {tab === 'stats' && <StatsPage />}
      {tab === 'more' && <MorePage currentUser={session.data.user} onDone={showToast} />}

      {toast && <div className="toast">{toast}</div>}

      <nav className="tabbar">
        {TABS.map((item) => (
          <button
            key={item.id}
            data-active={tab === item.id}
            onClick={() => setTab(item.id)}
            type="button"
          >
            <span>{item.icon}</span>
            {item.label}
          </button>
        ))}
      </nav>
    </div>
  )
}
