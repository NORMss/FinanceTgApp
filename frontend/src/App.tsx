import { useQuery } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiError, login } from './api'
import AddPage from './pages/AddPage'
import CategoriesPage from './pages/CategoriesPage'
import HistoryPage from './pages/HistoryPage'
import MorePage from './pages/MorePage'
import StatsPage from './pages/StatsPage'
import { isStandalone } from './telegram'

type Tab = 'add' | 'history' | 'stats' | 'more'
type Screen = Tab | 'categories'

const TABS: { id: Tab; icon: string; label: string }[] = [
  { id: 'add', icon: '➕', label: 'Добавить' },
  { id: 'history', icon: '📜', label: 'История' },
  { id: 'stats', icon: '📊', label: 'Отчёт' },
  { id: 'more', icon: '⚙️', label: 'Ещё' },
]

/**
 * Экран неудачного входа.
 *
 * Причину не показываем. Приложение приватное, и человек, увидевший этот экран, —
 * либо владелец (тогда точный ответ лежит в `docker compose logs app`), либо посторонний,
 * которому незачем знать, дело в белом списке, в подписи или в часах на сервере.
 * Различать эти случаи по тексту ошибки — прямая подсказка тому, кто подбирает доступ.
 *
 * Единственное исключение — «страница открыта вне Telegram»: это видно на клиенте
 * и без ответа сервера, а объяснение экономит владельцу вечер.
 */
function LoginError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const offline = error instanceof ApiError && error.status === 0

  return (
    <div className="center">
      <div>
        <p className="error">{offline ? 'Сервер недоступен' : 'Не удалось войти'}</p>
        {isStandalone ? (
          <p className="hint">
            Страница открыта вне Telegram. Запускайте приложение кнопкой в боте — иначе
            Telegram не передаёт данные для входа.
          </p>
        ) : (
          <p className="hint">
            {offline
              ? 'Не получилось связаться с сервером. Попробуйте ещё раз через минуту.'
              : 'Попробуйте открыть приложение заново из меню бота.'}
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
  const [screen, setScreen] = useState<Screen>('add')
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

  const me = session.data.user

  return (
    <div className="app">
      {screen === 'add' && <AddPage onDone={showToast} />}
      {screen === 'history' && <HistoryPage currentUserId={me.id} onDone={showToast} />}
      {screen === 'stats' && <StatsPage currentUserId={me.id} />}
      {screen === 'more' && (
        <MorePage
          currentUser={me}
          onDone={showToast}
          onOpenCategories={() => setScreen('categories')}
        />
      )}
      {/* Справочник — экран без своей вкладки: заходят туда редко,
          а пятая кнопка внизу отняла бы место у ежедневных */}
      {screen === 'categories' && (
        <CategoriesPage onBack={() => setScreen('more')} onDone={showToast} />
      )}

      {toast && <div className="toast">{toast}</div>}

      <nav className="tabbar">
        {TABS.map((item) => (
          <button
            key={item.id}
            data-active={screen === item.id}
            onClick={() => setScreen(item.id)}
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
