import { useMemo } from 'react'

import { buildTree, indexById } from '../categories'
import { haptic } from '../telegram'
import type { Category } from '../types'

interface Props {
  categories: Category[]
  value: string | null
  onChange: (id: string | null) => void
  /** Порядок корневых категорий: последние использованные идут первыми. */
  order?: string[]
}

/**
 * Выбор категории в два касания: сначала корень, затем — если у него есть
 * подкатегории — уточнение.
 *
 * Показывать всё дерево одним списком нельзя: тридцать чипсов «Пятёрочка», «Магнит»,
 * «Кофе» вперемешку с корнями невозможно просмотреть глазами. Поэтому подкатегории
 * появляются только у выбранной ветки. Остаться на корне тоже допустимо — не каждая
 * трата в «Продуктах» требует уточнения магазина.
 */
export default function CategoryPicker({ categories, value, onChange, order }: Props) {
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

  const selected = value ? byId.get(value) : undefined
  const activeRootId = selected?.parent_id ?? selected?.id ?? null
  const activeNode = tree.find((node) => node.category.id === activeRootId)

  const pick = (id: string | null) => {
    haptic()
    onChange(id)
  }

  return (
    <>
      <div className="chips">
        {tree.map(({ category, children }) => (
          <button
            key={category.id}
            type="button"
            className="chip"
            data-active={activeRootId === category.id}
            onClick={() => pick(activeRootId === category.id ? null : category.id)}
          >
            {category.icon} {category.name}
            {children.length > 0 && <span className="chip__more"> ›</span>}
          </button>
        ))}
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
    </>
  )
}
