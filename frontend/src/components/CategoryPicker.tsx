import { useLayoutEffect, useMemo, useRef, useState } from 'react'

import { buildTree, indexById } from '../categories'
import { haptic } from '../telegram'
import type { Category } from '../types'

interface Props {
  categories: Category[]
  value: string | null
  onChange: (id: string | null) => void
  /** Порядок корневых категорий: последние использованные идут первыми. */
  order?: string[]
  /** Свернуть список до трёх рядов. Форма ввода — да, шторка правки — нет: там
   *  экран и так короткий, а нужная категория уже выбрана. */
  collapsible?: boolean
}

/** Сколько рядов чипсов показываем свёрнутыми. */
const ROWS = 3
/** Должен совпадать с gap у .chips — по нему считается перенос строки. */
const GAP = 8

/**
 * Сколько чипсов влезет в ROWS рядов так, чтобы осталось место на «Ещё N».
 *
 * Раскладку считаем сами, а не полагаемся на overflow: hidden, потому что чипс
 * «Ещё» обязан стоять последним среди видимых, а не быть обрезанным вместе с ними.
 * Возвращает длину списка целиком, если все чипсы помещаются и прятать нечего.
 */
function fit(widths: number[], more: number, width: number): number {
  let row = 0
  let used = 0
  let best = 0

  for (let index = 0; index < widths.length; index += 1) {
    const chip = widths[index]
    if (used > 0 && used + GAP + chip > width) {
      row += 1
      used = 0
    }
    if (row >= ROWS) return best
    used = used > 0 ? used + GAP + chip : chip
    // «Ещё» встанет либо в остаток этого ряда, либо в следующий — если он есть
    if (row < ROWS - 1 || used + GAP + more <= width) best = index + 1
  }

  return widths.length
}

/** Ширины чипсов в порядке дерева, ширина чипса «Ещё» и ширина полосы. */
interface Metrics {
  widths: number[]
  more: number
  width: number
}

/**
 * Выбор категории в два касания: сначала корень, затем — если у него есть
 * подкатегории — уточнение.
 *
 * Показывать всё дерево одним списком нельзя: тридцать чипсов «Пятёрочка», «Магнит»,
 * «Кофе» вперемешку с корнями невозможно просмотреть глазами. Поэтому подкатегории
 * появляются только у выбранной ветки. Остаться на корне тоже допустимо — не каждая
 * трата в «Продуктах» требует уточнения магазина.
 *
 * Корней тоже бывает много, и развёрнутый список съедал полэкрана на телефоне.
 * Свёрнутый показывает три ряда — при сортировке по последнему использованию туда
 * попадает всё, чем пользуются каждый день, — а остальное открывает последний чипс.
 */
export default function CategoryPicker({
  categories,
  value,
  onChange,
  order,
  collapsible = false,
}: Props) {
  const byId = useMemo(() => indexById(categories), [categories])
  const tree = useMemo(() => {
    const nodes = buildTree(categories)
    if (!order?.length) return nodes
    const weight = new Map(order.map((id, index) => [id, index]))
    // Вес подкатегории поднимает и её родителя: если вчера платили в «Пятёрочке»,
    // ветка «Продукты» должна быть первой
    const rank = (node: (typeof nodes)[number]) =>
      Math.min(
        weight.get(node.category.id) ?? 999,
        ...node.children.map((child) => weight.get(child.id) ?? 999),
      )
    return [...nodes].sort((a, b) => rank(a) - rank(b))
  }, [categories, order])

  const [expanded, setExpanded] = useState(false)
  /** Ширины всех чипсов и полосы под них. null — ещё не измеряли. */
  const [metrics, setMetrics] = useState<Metrics | null>(null)
  const ruler = useRef<HTMLDivElement>(null)

  // Состав чипсов строкой: пересчитывать раскладку надо, когда меняются сами
  // категории или их порядок, а не на каждый рендер из-за нового массива
  const shape = tree.map((node) => node.category.id).join()

  useLayoutEffect(() => {
    const box = ruler.current
    if (!collapsible || !box) return

    const recalc = () => {
      const width = box.clientWidth
      const nodes = [...box.children] as HTMLElement[]
      if (!width || nodes.length < 2) return
      setMetrics({
        widths: nodes.slice(0, -1).map((node) => node.offsetWidth),
        more: nodes[nodes.length - 1].offsetWidth,
        width,
      })
    }

    recalc()
    // Ширина меняется от поворота экрана и от клавиатуры, поднимающей вёрстку
    const observer = new ResizeObserver(recalc)
    observer.observe(box)
    return () => observer.disconnect()
  }, [collapsible, shape])

  const selected = value ? byId.get(value) : undefined
  const activeRootId = selected?.parent_id ?? selected?.id ?? null
  const activeNode = tree.find((node) => node.category.id === activeRootId)
  const activeIndex = tree.findIndex((node) => node.category.id === activeRootId)

  const layout = useMemo(() => {
    const natural = tree.map((_, index) => index)
    if (!metrics) return { order: natural, room: tree.length }

    const room = fit(metrics.widths, metrics.more, metrics.width)
    if (activeIndex < room) return { order: natural, room }

    // Выбранное из свёрнутой части поднимаем в начало: иначе, свернувшись, список
    // оставил бы ряд подкатегорий без родителя. Порядок всё равно тот же, каким он
    // станет после сохранения — эта категория и есть последняя использованная
    const order = [activeIndex, ...natural.filter((index) => index !== activeIndex)]
    const widths = order.map((index) => metrics.widths[index])
    return { order, room: fit(widths, metrics.more, metrics.width) }
  }, [tree, metrics, activeIndex])

  const hidden = Math.max(0, tree.length - layout.room)
  const clamped = collapsible && hidden > 0 && !expanded
  const shown = clamped ? layout.order.slice(0, layout.room).map((index) => tree[index]) : tree

  const pick = (id: string | null) => {
    haptic()
    onChange(id)
  }

  const chip = (node: (typeof tree)[number]) => (
    <button
      key={node.category.id}
      type="button"
      className="chip"
      data-active={activeRootId === node.category.id}
      onClick={() => pick(activeRootId === node.category.id ? null : node.category.id)}
    >
      {node.category.icon} {node.category.name}
      {node.children.length > 0 && <span className="chip__more"> ›</span>}
    </button>
  )

  return (
    <div className="picker">
      {/* Линейка: копии всех чипсов вне потока, по ней меряются ширины — у чипса,
          убранного из разметки, ширины уже не спросишь.
          Не кнопки и не .chip намеренно: иначе любой поиск по `.chip` — в тестах,
          в съёмке скриншотов — находил бы сначала невидимую копию */}
      {collapsible && (
        <div className="picker__ruler" ref={ruler} aria-hidden="true">
          {tree.map((node) => (
            <i key={node.category.id}>
              {node.category.icon} {node.category.name}
              {node.children.length > 0 && <span className="chip__more"> ›</span>}
            </i>
          ))}
          {/* Самая длинная из подписей: «Свернуть» короче, чем «Ещё» с числом */}
          <i>Ещё {tree.length}</i>
        </div>
      )}

      <div className="chips chips--roots">
        {shown.map(chip)}
        {collapsible && hidden > 0 && (
          <button
            type="button"
            className="chip chip--ghost"
            onClick={() => {
              haptic()
              setExpanded((current) => !current)
            }}
          >
            {clamped ? `Ещё ${hidden}` : 'Свернуть'}
          </button>
        )}
      </div>

      {activeNode && activeNode.children.length > 0 && (
        <div className="chips chips--nested">
          <button
            type="button"
            className="chip chip--ghost"
            data-active={selected?.id === activeNode.category.id}
            onClick={() => pick(activeNode.category.id)}
          >
            без уточнения
          </button>
          {activeNode.children.map((child) => (
            <button
              key={child.id}
              type="button"
              className="chip chip--ghost"
              data-active={value === child.id}
              onClick={() => pick(child.id)}
            >
              {child.icon} {child.name}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
