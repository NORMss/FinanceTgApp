import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'

import { api } from '../api'
import { buildTree } from '../categories'
import ErrorNote from '../components/ErrorNote'
import { haptic, notify } from '../telegram'
import type { Category, CategoryKind } from '../types'

interface Props {
  onBack: () => void
  onDone: (message: string) => void
}

// Быстрый набор значков. Полноценную клавиатуру эмодзи открывает системное поле ввода —
// эти кнопки просто закрывают девять случаев из десяти в одно касание.
const QUICK_ICONS = [
  '🛒', '🍽', '☕', '🚕', '🚇', '⛽', '🏠', '💡', '💊', '🏥',
  '🎬', '🎮', '👕', '💅', '📱', '🎁', '✈️', '🐾', '📚', '🧒',
  '💳', '🔧', '🌿', '🍺', '💰', '📦',
]

interface FormState {
  id?: string
  name: string
  icon: string
  parentId: string | null
  kind: CategoryKind
}

const EMPTY: FormState = { name: '', icon: '', parentId: null, kind: 'expense' }

/**
 * Управление справочником: создать категорию или подкатегорию, переименовать,
 * поменять значок, спрятать.
 *
 * Экран намеренно отдельный и не показывается при вводе траты: справочник правят
 * раз в месяц, а трату записывают каждый день, и мешать эти два сценария нельзя.
 */
export default function CategoriesPage({ onBack, onDone }: Props) {
  const queryClient = useQueryClient()
  const [kind, setKind] = useState<CategoryKind>('expense')
  const [form, setForm] = useState<FormState | null>(null)

  const categories = useQuery({
    queryKey: ['categories', 'manage'],
    queryFn: () => api.categories(),
  })

  const tree = useMemo(
    () => buildTree((categories.data ?? []).filter((item) => item.kind === kind)),
    [categories.data, kind],
  )

  const refresh = () => queryClient.invalidateQueries()

  const save = useMutation({
    mutationFn: (state: FormState) =>
      state.id
        ? api.updateCategory(state.id, { name: state.name.trim(), icon: state.icon })
        : api.createCategory({
            name: state.name.trim(),
            icon: state.icon,
            kind: state.kind,
            parent_id: state.parentId,
          }),
    onSuccess: (_, state) => {
      notify('success')
      onDone(state.id ? 'Категория изменена' : 'Категория добавлена')
      setForm(null)
      refresh()
    },
    onError: () => notify('error'),
  })

  const hide = useMutation({
    mutationFn: (category: Category) => api.deleteCategory(category.id),
    onSuccess: (result) => {
      notify('success')
      onDone(
        result.result === 'deleted'
          ? 'Категория удалена'
          : 'Категория скрыта — на неё ссылаются операции',
      )
      refresh()
    },
    onError: () => notify('error'),
  })

  const editing = form?.id !== undefined

  return (
    <div className="page">
      <div className="topbar">
        <button className="btn btn--ghost btn--slim" type="button" onClick={onBack}>
          ‹ Назад
        </button>
        <b>Категории</b>
      </div>

      <div className="segmented">
        {(['expense', 'income'] as const).map((value) => (
          <button
            key={value}
            type="button"
            data-active={kind === value}
            onClick={() => {
              haptic()
              setKind(value)
              setForm(null)
            }}
          >
            {value === 'expense' ? 'Расходы' : 'Доходы'}
          </button>
        ))}
      </div>

      <ErrorNote error={categories.error ?? save.error ?? hide.error} />

      {form && (
        <div className="card">
          <p className="section-title" style={{ margin: '0 0 10px' }}>
            {editing
              ? 'Правка категории'
              : form.parentId
                ? 'Новая подкатегория'
                : 'Новая категория'}
          </p>

          <div className="icon-row">
            <input
              className="field field--icon"
              value={form.icon}
              maxLength={16}
              placeholder="🙂"
              onChange={(event) => setForm({ ...form, icon: event.target.value })}
              aria-label="Значок"
            />
            <input
              className="field"
              value={form.name}
              maxLength={64}
              placeholder="Название"
              autoFocus
              onChange={(event) => setForm({ ...form, name: event.target.value })}
              aria-label="Название категории"
            />
          </div>

          <div className="chips chips--icons">
            {QUICK_ICONS.map((icon) => (
              <button
                key={icon}
                type="button"
                className="chip chip--icon"
                data-active={form.icon === icon}
                onClick={() => {
                  haptic()
                  setForm({ ...form, icon })
                }}
              >
                {icon}
              </button>
            ))}
          </div>

          <div className="sheet__actions">
            <button className="btn btn--ghost" type="button" onClick={() => setForm(null)}>
              Отмена
            </button>
            <button
              className="btn"
              type="button"
              disabled={!form.name.trim() || save.isPending}
              onClick={() => save.mutate(form)}
            >
              {save.isPending ? 'Сохраняем…' : 'Сохранить'}
            </button>
          </div>
        </div>
      )}

      {tree.map(({ category, children }) => (
        <div className="card card--tight" key={category.id}>
          <div className="row">
            <div className="row__icon">{category.icon || '•'}</div>
            <div className="row__body">
              <div className="row__title">{category.name}</div>
              <div className="row__sub">
                {children.length > 0 ? `${children.length} подкатегорий` : 'без подкатегорий'}
              </div>
            </div>
            <div className="row__tools">
              <button
                type="button"
                className="icon-btn"
                title="Переименовать"
                onClick={() =>
                  setForm({
                    id: category.id,
                    name: category.name,
                    icon: category.icon,
                    parentId: category.parent_id,
                    kind,
                  })
                }
              >
                ✏️
              </button>
              <button
                type="button"
                className="icon-btn"
                title="Добавить подкатегорию"
                onClick={() => setForm({ ...EMPTY, parentId: category.id, kind })}
              >
                ➕
              </button>
              <button
                type="button"
                className="icon-btn"
                title="Скрыть"
                disabled={hide.isPending}
                onClick={() => hide.mutate(category)}
              >
                🗑
              </button>
            </div>
          </div>

          {children.map((child) => (
            <div className="row row--nested" key={child.id}>
              <div className="row__icon row__icon--small">{child.icon || '·'}</div>
              <div className="row__body">
                <div className="row__title">{child.name}</div>
              </div>
              <div className="row__tools">
                <button
                  type="button"
                  className="icon-btn"
                  title="Переименовать"
                  onClick={() =>
                    setForm({
                      id: child.id,
                      name: child.name,
                      icon: child.icon,
                      parentId: child.parent_id,
                      kind,
                    })
                  }
                >
                  ✏️
                </button>
                <button
                  type="button"
                  className="icon-btn"
                  title="Скрыть"
                  disabled={hide.isPending}
                  onClick={() => hide.mutate(child)}
                >
                  🗑
                </button>
              </div>
            </div>
          ))}
        </div>
      ))}

      <button
        className="btn btn--ghost"
        type="button"
        onClick={() => setForm({ ...EMPTY, kind })}
      >
        + Новая категория
      </button>

      <p className="hint">
        Категорию, на которую уже ссылаются операции, удалить нельзя — она скрывается
        из списков, а история за прошлые месяцы остаётся разбитой как была.
      </p>
    </div>
  )
}
