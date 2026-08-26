/**
 * Состояние, переживающее закрытие приложения.
 *
 * Mini App открывают на двадцать секунд и закрывают. Отчёт, который каждый раз
 * встречает человека сбросом периода и снятыми исключениями, заставляет собирать
 * вид заново перед каждым взглядом — и им перестают пользоваться уже на третий раз.
 *
 * Хранится в localStorage, а не на сервере: это «где я остановился», а не настройка.
 * Потеря такого состояния не стоит ни миграции, ни запроса на старте. Именованные
 * наборы фильтров — другое дело, они лежат в базе (см. api.reportViews).
 *
 * Ключ включает идентификатор пользователя: в одном браузере может открыться
 * второй участник, и чужие исключения на его отчёте выглядели бы поломкой.
 */

import { useCallback, useEffect, useState } from 'react'

const PREFIX = 'financetg'

function read<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key)
    return raw === null ? fallback : (JSON.parse(raw) as T)
  } catch {
    // Приватный режим, переполненное хранилище, испорченный JSON — во всех случаях
    // умолчание лучше, чем белый экран из-за настройки
    return fallback
  }
}

export function useSticky<T>(name: string, userId: string, fallback: T) {
  const key = `${PREFIX}:${userId}:${name}`
  const [value, setValue] = useState<T>(() => read(key, fallback))

  useEffect(() => {
    try {
      window.localStorage.setItem(key, JSON.stringify(value))
    } catch {
      // Не смогли запомнить — работаем дальше без памяти
    }
  }, [key, value])

  const reset = useCallback(() => setValue(fallback), [fallback])
  return [value, setValue, reset] as const
}
