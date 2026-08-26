import { useMemo, useState } from 'react'

import { buildTree } from '../categories'
import { formatMoney } from '../format'
import { haptic } from '../telegram'
import type { Category, CategoryTotal, Tag } from '../types'

/** Псевдоидентификатор строки «Без категории»: настоящего id у неё нет. */
export const UNCATEGORIZED = '__none__'

interface Props {
  categories: Category[]
  /** Суммы текущего периода — чтобы было видно, что именно скрывается. */
  totals: CategoryTotal[]
  tags: Tag[]
  excluded: string[]
  excludeUncategorized: boolean
  excludedTags: string[]
  onApply: (next: {
    excluded: string[]
    excludeUncategorized: boolean
    excludedTags: string[]
  }) => void
  onClose: () => void
}

/**
 * Что вычесть из отчёта.
 *
 * Множественный выбор, поэтому не подходит `CategoryPicker`: тот одиночный и заточен
 * под ввод траты, где выбирают ровно одно. Здесь наоборот — отмечают несколько
 * и почти никогда не отмечают ничего заново, поэтому список плоский и весь на виду,
 * без раскрытия веток.
 *
 * Рядом с каждой строкой стоит сумма за текущий период: «скрыть Жильё» без цифры —
 * это выбор вслепую, а с цифрой сразу видно, что уйдёт 42 200 из 100 552.
 */
export default function CategoryFilterSheet({
  categories,
  totals,
  tags,
  excluded,
  excludeUncategorized,
  excludedTags,
  onApply,
  onClose,
}: Props) {
  const [picked, setPicked] = useState<Set<string>>(
    () => new Set(excludeUncategorized ? [...excluded, UNCATEGORIZED] : excluded),
  )
  const [pickedTags, setPickedTags] = useState<Set<string>>(() => new Set(excludedTags))

  const amounts = useMemo(
    () => new Map(totals.map((item) => [item.category_id ?? UNCATEGORIZED, item.amount_minor])),
    [totals],
  )
  const tree = useMemo(() => buildTree(categories), [categories])

  const toggle = (id: string) => {
    haptic()
    setPicked((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleTag = (name: string) => {
    haptic()
    setPickedTags((current) => {
      const next = new Set(current)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  // Сумма считается только по корням и по подкатегориям вне скрытых веток: скрытый
  // родитель уже унёс своих детей, и складывать их второй раз значит обещать
  // вычесть больше, чем в отчёте вообще есть
  const hidden = useMemo(() => {
    let total = 0
    for (const id of picked) {
      const category = categories.find((item) => item.id === id)
      if (category?.parent_id && picked.has(category.parent_id)) continue
      total += amounts.get(id) ?? 0
    }
    return total
  }, [picked, categories, amounts])

  // Сумму по меткам клиент не знает: метка режет поперёк категорий, и сложить её
  // из строк отчёта нельзя. Поэтому цифру обещаем только там, где она известна,
  // а сам факт выбора кнопка обязана показать в любом случае
  const nothingPicked = picked.size === 0 && pickedTags.size === 0

  const apply = () => {
    const ids = [...picked].filter((id) => id !== UNCATEGORIZED)
    onApply({
      excluded: ids,
      excludeUncategorized: picked.has(UNCATEGORIZED),
      excludedTags: [...pickedTags],
    })
  }

  const clear = () => {
    haptic()
    setPicked(new Set())
    setPickedTags(new Set())
  }

  const renderRow = (category: Category, nested: boolean) => {
    const amount = amounts.get(category.id) ?? 0
    // Дети скрытого родителя отмечаются автоматически: ветка уходит целиком,
    // и оставлять их галочки пустыми значит врать про то, что произойдёт
    const viaParent = Boolean(category.parent_id && picked.has(category.parent_id))
    return (
      <label className={`row row--tappable${nested ? ' row--nested' : ''}`} key={category.id}>
        <div className={`row__icon${nested ? ' row__icon--small' : ''}`}>
          {category.icon || '•'}
        </div>
        <div className="row__body">
          <div className="row__title">{category.name}</div>
          {amount > 0 && <div className="row__sub">{formatMoney(amount)} за период</div>}
        </div>
        <input
          type="checkbox"
          className="check"
          checked={picked.has(category.id) || viaParent}
          disabled={viaParent}
          onChange={() => toggle(category.id)}
          aria-label={`Скрыть ${category.name}`}
        />
      </label>
    )
  }

  return (
    <div className="sheet-backdrop" onClick={onClose} role="presentation">
      <div className="sheet" onClick={(event) => event.stopPropagation()} role="dialog">
        <div className="sheet__grip" />

        <p className="section-title" style={{ margin: 0 }}>
          Что не показывать в отчёте
        </p>
        <p className="hint" style={{ marginTop: 0 }}>
          Скрытое вычитается из итога, а не просто пропадает из списка. Сумму видно
          под расходами — чтобы отчёт всегда сходился.
        </p>

        <div className="card card--tight">
          {tree.map(({ category, children }) => (
            <div key={category.id}>
              {renderRow(category, false)}
              {children.map((child) => renderRow(child, true))}
            </div>
          ))}

          <label className="row row--tappable">
            <div className="row__icon">•</div>
            <div className="row__body">
              <div className="row__title">Без категории</div>
              {(amounts.get(UNCATEGORIZED) ?? 0) > 0 && (
                <div className="row__sub">
                  {formatMoney(amounts.get(UNCATEGORIZED) ?? 0)} за период
                </div>
              )}
            </div>
            <input
              type="checkbox"
              className="check"
              checked={picked.has(UNCATEGORIZED)}
              onChange={() => toggle(UNCATEGORIZED)}
              aria-label="Скрыть операции без категории"
            />
          </label>
        </div>

        {/* Метки отвечают на «в рамках чего»: отпуск размазан по десяти категориям,
            и вычесть его исключением категорий невозможно */}
        {tags.length > 0 && (
          <>
            <p className="section-title" style={{ marginBottom: 0 }}>
              Скрыть по метке
            </p>
            <div className="chips">
              {tags.map((tag) => (
                <button
                  key={tag.name}
                  type="button"
                  className="chip chip--ghost"
                  data-active={pickedTags.has(tag.name)}
                  onClick={() => toggleTag(tag.name)}
                >
                  {tag.name}
                </button>
              ))}
            </div>
          </>
        )}

        <div className="sheet__actions">
          <button className="btn btn--ghost" type="button" onClick={clear}>
            Показать всё
          </button>
          <button className="btn" type="button" onClick={apply}>
            {nothingPicked ? 'Готово' : hidden > 0 ? `Скрыть ${formatMoney(hidden)}` : 'Скрыть'}
          </button>
        </div>
      </div>
    </div>
  )
}
