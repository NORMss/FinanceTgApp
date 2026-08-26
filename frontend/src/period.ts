/**
 * Период отчёта: пресет, конкретный месяц или произвольный диапазон.
 *
 * Три формы вместо одной, потому что это три разных вопроса. Пресет — «покажи как
 * обычно», и он же умолчание. Конкретный месяц — «а что было в марте», и листать его
 * стрелками быстрее, чем каждый раз открывать календарь. Произвольный диапазон нужен
 * реже всех, но без него нельзя посмотреть поездку с 3 по 11 июня.
 *
 * Наружу все три превращаются в те параметры, которые бэкенд понимает с самого начала:
 * `?period=` для пресета и `?from=&to=` для остального.
 */

import type { Period } from './types'

export type Range =
  | { kind: 'preset'; preset: Period }
  /** anchor — «2026-08». Календарный месяц целиком. */
  | { kind: 'month'; anchor: string }
  /** Границы включительно, обе в виде «2026-08-01». */
  | { kind: 'custom'; from: string; to: string }

export const DEFAULT_RANGE: Range = { kind: 'preset', preset: 'month' }

const MONTHS_GENITIVE = [
  'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
  'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря',
]

const MONTHS_NOMINATIVE = [
  'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
  'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь',
]

function pad(value: number): string {
  return value.toString().padStart(2, '0')
}

/** Сколько дней в месяце: нулевой день следующего — это последний день текущего. */
function daysIn(year: number, month: number): number {
  return new Date(year, month, 0).getDate()
}

export function monthAnchor(date: Date = new Date()): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}`
}

/** Сдвигает якорь месяца на `delta` месяцев: «2026-01» + (-1) = «2025-12». */
export function shiftAnchor(anchor: string, delta: number): string {
  const [year, month] = anchor.split('-').map(Number)
  const total = year * 12 + (month - 1) + delta
  return `${Math.floor(total / 12)}-${pad((total % 12) + 1)}`
}

/** Параметры запроса. Пустые поля api.query() отбросит сам. */
export function rangeQuery(range: Range): { period?: Period; from?: string; to?: string } {
  if (range.kind === 'preset') return { period: range.preset }
  if (range.kind === 'custom') return { from: range.from, to: range.to }

  const [year, month] = range.anchor.split('-').map(Number)
  return {
    from: `${range.anchor}-01`,
    to: `${range.anchor}-${pad(daysIn(year, month))}`,
  }
}

/** Ключ кэша react-query. Массивы в ключах сравниваются по значению, объекты тоже. */
export function rangeKey(range: Range): string {
  const query = rangeQuery(range)
  return query.period ?? `${query.from}..${query.to}`
}

/**
 * Подпись периода — из того, что ответил сервер, а не из того, что мы просили.
 *
 * Это не педантизм: пресет «Месяц» превращается в конкретные даты на сервере, и если
 * когда-нибудь границы начнут считаться по часовому поясу человека, подпись поедет
 * вместе с цифрами сама. Считать её на клиенте значит однажды получить заголовок
 * «Август» над сентябрьскими деньгами.
 *
 * Компоненты берутся в UTC: границы периода — это UTC-полночь по построению,
 * и локальные getDate() в поясе западнее Гринвича показали бы предыдущий день.
 */
export function formatRange(startIso: string, endIso: string): string {
  const start = new Date(startIso)
  // Правая граница открытая: «весь август» заканчивается первым сентября в ноль часов
  const finish = new Date(new Date(endIso).getTime() - 86_400_000)

  if (start.getUTCFullYear() <= 1970) return 'Всё время'

  const sameMonth =
    start.getUTCMonth() === finish.getUTCMonth() &&
    start.getUTCFullYear() === finish.getUTCFullYear()

  if (sameMonth && start.getUTCDate() === 1 && finish.getUTCDate() === daysIn(
    start.getUTCFullYear(), start.getUTCMonth() + 1,
  )) {
    const year =
      start.getUTCFullYear() === new Date().getFullYear() ? '' : ` ${start.getUTCFullYear()}`
    return `${MONTHS_NOMINATIVE[start.getUTCMonth()]}${year}`
  }

  if (sameMonth) {
    return `${start.getUTCDate()}–${finish.getUTCDate()} ${MONTHS_GENITIVE[start.getUTCMonth()]}`
  }

  return (
    `${start.getUTCDate()} ${MONTHS_GENITIVE[start.getUTCMonth()]} — ` +
    `${finish.getUTCDate()} ${MONTHS_GENITIVE[finish.getUTCMonth()]}`
  )
}

/** Сколько дней в периоде и сколько из них уже прошло — для темпа трат и прогноза. */
export function progress(startIso: string, endIso: string): { days: number; passed: number } {
  const start = new Date(startIso).getTime()
  const end = new Date(endIso).getTime()
  const days = Math.max(1, Math.round((end - start) / 86_400_000))
  // Будущий период ещё не начался, прошедший закончился весь — обрезаем с обеих сторон
  const elapsed = Math.ceil((Date.now() - start) / 86_400_000)
  return { days, passed: Math.min(days, Math.max(1, elapsed)) }
}
