/**
 * День операции.
 *
 * Время в этом приложении не спрашивают. «Когда» для траты — это дата: часы и минуты
 * никто не помнит уже к вечеру, а спросить их значит поставить лишнее препятствие
 * перед единственным полем, от которого зависит, в какой месяц попадут деньги.
 *
 * Наружу поэтому ходит день в виде «2026-08-26» — ровно то, что понимает
 * <input type="date">, — а время подставляется само: у новой записи текущее,
 * у правки старой остаётся прежним.
 */

const MONTHS_SHORT = [
  'янв', 'фев', 'мар', 'апр', 'мая', 'июн',
  'июл', 'авг', 'сен', 'окт', 'ноя', 'дек',
]

function pad(value: number): string {
  return value.toString().padStart(2, '0')
}

/**
 * «2026-08-26» для даты.
 *
 * Компоненты берём локальные, а не из toISOString(): восточнее Гринвича UTC-дата
 * вечером уже завтрашняя, и «Сегодня» подставляло бы завтрашний день.
 */
export function dayKey(date: Date = new Date()): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

/** День операции из её ISO-времени. */
export function dayOf(iso: string): string {
  return dayKey(new Date(iso))
}

/** Сдвиг на дни: «2026-03-01» + (-1) = «2026-02-28». Переносы считает сам Date. */
export function shiftDay(key: string, delta: number): string {
  const [year, month, day] = key.split('-').map(Number)
  return dayKey(new Date(year, month - 1, day + delta))
}

/** «12 авг», а для прошлого года — «12 авг 2025». */
export function shortDay(key: string): string {
  const [year, month, day] = key.split('-').map(Number)
  const suffix = year === new Date().getFullYear() ? '' : ` ${year}`
  return `${day} ${MONTHS_SHORT[month - 1]}${suffix}`
}

/** День `key` со временем из `base`. Три компонента одним вызовом: setDate(31)
 *  в тридцатидневном месяце уехал бы на следующий, а так переполнения не возникает. */
function at(key: string, base: Date): string {
  const [year, month, day] = key.split('-').map(Number)
  const moment = new Date(base)
  moment.setFullYear(year, month - 1, day)
  return moment.toISOString()
}

/**
 * Момент операции для дня, выбранного задним числом, — полдень по местному времени.
 *
 * Не текущее время суток: границы периодов сервер режет по UTC, и запись, сделанная
 * в час ночи, с текущим временем уехала бы на предыдущие сутки — а первого числа
 * вместе с ними и в прошлый месяц. Полдень остаётся тем же днём в любом реальном
 * часовом поясе, а часы человеку всё равно не важны.
 */
export function isoForDay(key: string): string {
  const noon = new Date()
  noon.setHours(12, 0, 0, 0)
  return at(key, noon)
}

/**
 * Тот же момент, но перенесённый на другой день: время операции остаётся прежним.
 *
 * Для правки уже записанного. Время там настоящее — то, в которое трату внесли,
 * — и терять его при переносе на соседний день незачем.
 */
export function withDay(iso: string, key: string): string {
  return at(key, new Date(iso))
}
