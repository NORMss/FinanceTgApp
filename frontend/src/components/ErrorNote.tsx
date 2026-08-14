import { ApiError } from '../api'

/**
 * Единый вывод ошибки запроса.
 *
 * Раньше упавший запрос выглядел как пустой экран — не отличить «данных нет»
 * от «сервер не ответил». Код статуса показываем всегда: по нему сразу понятно,
 * это протухшая сессия (401), недоступный бэкенд (0) или ошибка внутри (5xx).
 */
export default function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null

  const status = error instanceof ApiError ? error.status : 0
  const text = error instanceof Error ? error.message : String(error)

  return (
    <div className="card">
      <p className="error" style={{ margin: 0 }}>
        {status ? `Ошибка ${status}` : 'Сервер недоступен'}
      </p>
      <p className="hint" style={{ marginBottom: 0 }}>
        {text}
      </p>
    </div>
  )
}
