/**
 * Форматирование денег и дат.
 *
 * Внутри приложения суммы — только целые копейки. Деление на 100 происходит один раз,
 * в момент вывода на экран, и результат сразу превращается в строку.
 */

const NBSP = ' '

export function formatMoney(minor: number, options: { sign?: boolean } = {}): string {
  const negative = minor < 0
  const abs = Math.abs(minor)
  const whole = Math.trunc(abs / 100)
  const cents = abs % 100

  const grouped = whole.toString().replace(/\B(?=(\d{3})+(?!\d))/g, NBSP)
  const body = cents ? `${grouped},${cents.toString().padStart(2, '0')}` : grouped

  if (negative) return `−${NBSP}${body}`
  return options.sign ? `+${NBSP}${body}` : body
}

/** Строка ввода «1 234,56» -> та же строка, но пригодная для отправки на сервер. */
export function normalizeAmountInput(raw: string): string {
  return raw.replace(/[^\d.,]/g, '').replace(',', '.')
}

export function isValidAmount(raw: string): boolean {
  const value = normalizeAmountInput(raw)
  return /^\d+(\.\d{1,2})?$/.test(value) && Number(value) > 0
}

/** Копейки -> строка для поля ввода: «1234,56». Разряды не разделяем — их пришлось бы
 * вычищать при каждом нажатии клавиши. */
export function toAmountInput(minor: number): string {
  const abs = Math.abs(minor)
  const cents = abs % 100
  const whole = Math.trunc(abs / 100)
  return cents ? `${whole},${cents.toString().padStart(2, '0')}` : String(whole)
}

/** Строка ввода -> копейки. Нужна, чтобы сравнить введённое с уже сохранённым
 * без плавающей точки: 0.1 + 0.2 в JavaScript даёт не то, что ожидается. */
export function toMinor(raw: string): number {
  const [whole, fraction = ''] = normalizeAmountInput(raw).split('.')
  return Number(whole || 0) * 100 + Number(fraction.padEnd(2, '0').slice(0, 2) || 0)
}

const MONTHS = [
  'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
  'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря',
]

export function formatDay(iso: string): string {
  const date = new Date(iso)
  const today = new Date()
  const yesterday = new Date(today.getTime() - 86_400_000)

  const sameDay = (a: Date, b: Date) => a.toDateString() === b.toDateString()
  if (sameDay(date, today)) return 'Сегодня'
  if (sameDay(date, yesterday)) return 'Вчера'

  const year = date.getFullYear() === today.getFullYear() ? '' : ` ${date.getFullYear()}`
  return `${date.getDate()} ${MONTHS[date.getMonth()]}${year}`
}

export function formatTime(iso: string): string {
  const date = new Date(iso)
  return `${date.getHours().toString().padStart(2, '0')}:${date
    .getMinutes()
    .toString()
    .padStart(2, '0')}`
}

export const PERIOD_LABELS: Record<string, string> = {
  week: 'Неделя',
  month: 'Месяц',
  prev_month: 'Прошлый',
  '30d': '30 дней',
  year: 'Год',
  all: 'Всё время',
}
