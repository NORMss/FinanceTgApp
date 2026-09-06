import { ApiError, isTransient } from '../api'

/**
 * Единый вывод ошибки запроса.
 *
 * Раньше упавший запрос выглядел как пустой экран — не отличить «данных нет»
 * от «сервер не ответил». Код статуса показываем всегда: по нему сразу понятно,
 * это протухшая сессия (401), недоступный бэкенд (0) или ошибка внутри (5xx).
 *
 * У 502/503/504 своё объяснение. Голое «Ошибка 502» с текстом от прокси выглядит
 * как поломка приложения, хотя означает ровно обратное: приложение перезапускается,
 * до него не достучались, и через полминуты всё будет на месте. Запросы к этому
 * моменту уже повторились сами (см. retryTransient), так что если сообщение всё-таки
 * появилось — перезапуск затянулся, и единственное разумное действие это подождать.
 */
export default function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null

  const status = error instanceof ApiError ? error.status : 0
  const text = error instanceof Error ? error.message : String(error)
  const transient = isTransient(error)

  return (
    <div className="card">
      <p className="error" style={{ margin: 0 }}>
        {transient ? 'Сервер недоступен' : `Ошибка ${status}`}
      </p>
      <p className="hint" style={{ marginBottom: 0 }}>
        {transient
          ? `Приложение не отвечает — похоже, перезапускается. Попробуйте через минуту.${
              status ? ` (${status})` : ''
            }`
          : text}
      </p>
    </div>
  )
}
