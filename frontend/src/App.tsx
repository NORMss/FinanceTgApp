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

/**
 * Экран неудачного входа.
 *
 * Показываем код ответа и подсказку под каждую причину: «не получилось войти» без деталей
 * не даёт понять, дело в белом списке, в токене бота или в том, что страницу открыли
 * в обычном браузере, — а лезть в логи сервера ради этого приходится каждый раз.
 */
const LOGIN_HINTS: Record<number, string> = {
  0: 'Приложение не достучалось до сервера. Проверьте, что контейнер запущен и что прокси проксирует /api на него.',
  401: 'Подпись initData не сошлась. Обычно BOT_TOKEN на сервере принадлежит другому боту — не тому, из меню которого открыто приложение. Реже — сбитые часы на сервере.',
  403: 'Ваш Telegram ID не указан в ALLOWED_TELEGRAM_IDS. Добавьте его в .env и пересоздайте контейнер.',
  500: 'Ошибка на сервере. Подробности — в логах: docker compose logs app',
}

function LoginError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const status = error instanceof ApiError ? error.status : -1
  const detail = error instanceof Error ? error.message : String(error)

  return (
    <div className="center">
      <div>
        <p className="error">
          {status > 0 ? `Не получилось войти — сервер ответил ${status}` : 'Сервер недоступен'}
        </p>
        <p className="hint">{LOGIN_HINTS[status] ?? detail}</p>
        {/* Ответ сервера показываем всегда: подсказка объясняет типичный случай,
            а точную причину видно только здесь */}
        {LOGIN_HINTS[status] && <p className="hint">Ответ сервера: {detail}</p>}
        {isStandalone && (
          <p className="hint">
            Страница открыта вне Telegram, поэтому initData пустая. Запускайте приложение
            кнопкой в боте.
          </p>
        )}
        <button className="btn btn--ghost" type="button" onClick={onRetry}>
          Повторить
        </button>
      </div>
    </div>
  )
}

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
    return <LoginError error={session.error} onRetry={() => session.refetch()} />
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
