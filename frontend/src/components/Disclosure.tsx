import { type ReactNode, useState } from 'react'

import { haptic } from '../telegram'

interface Props {
  /** Что это за строка — видно всегда. */
  title: string
  /** Что в ней уже выбрано или введено. Показывается свёрнутой, чтобы не разворачивать
   *  ради проверки. */
  summary?: string
  /** Развернуть сразу — когда внутри уже стоит непустое значение. */
  defaultOpen?: boolean
  children: ReactNode
}

/**
 * Строка, раскрывающаяся вниз.
 *
 * Нужна там, где поле важно, но заполняется в одной записи из десяти: комментарий,
 * метки, фильтр по счёту. Такое поле, показанное всегда, отнимает высоту у того,
 * ради чего экран открывают, — а спрятанное совсем перестаёт существовать.
 * Свёрнутая строка решает оба: место занимает одну строку, а значение внутри
 * видно по подписи справа.
 */
export default function Disclosure({ title, summary, defaultOpen = false, children }: Props) {
  const [open, setOpen] = useState(defaultOpen)

  return (
    <div className="disclosure" data-open={open}>
      <button
        type="button"
        className="disclosure__head"
        aria-expanded={open}
        onClick={() => {
          haptic()
          setOpen((current) => !current)
        }}
      >
        <span className="disclosure__title">{title}</span>
        {!open && summary && <span className="disclosure__summary">{summary}</span>}
        <span className="disclosure__chevron" aria-hidden="true">
          ›
        </span>
      </button>
      {open && <div className="disclosure__body">{children}</div>}
    </div>
  )
}
