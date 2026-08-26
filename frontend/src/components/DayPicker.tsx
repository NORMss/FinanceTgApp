import { dayKey, shiftDay, shortDay } from '../day'
import { haptic } from '../telegram'

interface Props {
  /** Выбранный день, «2026-08-26». */
  value: string
  onChange: (day: string) => void
}

/**
 * Когда была трата: «Другая», «Вчера», «Сегодня».
 *
 * Дата — единственное поле формы, ошибка в котором портит отчёт молча: сумма
 * и категория видны в истории и бросаются в глаза, а чек, записанный на день
 * позже, просто уезжает в другой месяц. Поэтому выбор дня стоит прямо под суммой
 * и виден всегда, а не прячется за «подробностями».
 *
 * Кнопок ровно три, потому что вносят задним числом почти всегда вчерашнее —
 * вечерний чек, который забыли записать. Всё, что дальше, открывает календарь.
 *
 * Календарь открывает сам <input type="date">, растянутый поверх кнопки: вызывать
 * showPicker() нельзя, его нет в вебвью старых телефонов, а невидимое поле поверх
 * кнопки работает везде и отдаёт родной выбор даты платформы.
 */
export default function DayPicker({ value, onChange }: Props) {
  const today = dayKey()
  const yesterday = shiftDay(today, -1)
  const custom = value !== today && value !== yesterday

  const pick = (day: string) => {
    haptic()
    onChange(day)
  }

  return (
    <div className="segmented segmented--soft">
      <label data-active={custom}>
        {custom ? shortDay(value) : 'Другая'}
        <input
          type="date"
          value={value}
          // Иначе браузер восстановит дату прошлой сессии при перезагрузке страницы,
          // и приложение молча откроется на вчерашнем дне
          autoComplete="off"
          // Пустое значение приходит, когда дату стёрли в календаре — день без даты
          // приложению не нужен, оставляем прежний
          onChange={(event) => event.target.value && pick(event.target.value)}
          aria-label="Другая дата"
        />
      </label>
      <button
        type="button"
        data-active={value === yesterday}
        onClick={() => pick(yesterday)}
      >
        Вчера
      </button>
      <button type="button" data-active={value === today} onClick={() => pick(today)}>
        Сегодня
      </button>
    </div>
  )
}
