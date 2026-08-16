import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'

import { api } from '../api'
import { buildTree, fullName, indexById } from '../categories'
import ErrorNote from '../components/ErrorNote'
import { haptic, notify } from '../telegram'
import type { Category, CategoryKind } from '../types'

/** Значение в списке замены, означающее «заведите новую категорию под эти операции». */
const NEW_CATEGORY = '__new__'

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

type Forms = [string, string, string]

/** Какую из трёх русских форм брать: [одна, две, пять]. */
function pluralIndex(count: number): 0 | 1 | 2 {
  const tail = count % 100
  const last = count % 10
  if (tail > 4 && tail < 21) return 2
  if (last === 1) return 0
  if (last > 1 && last < 5) return 1
  return 2
}

/** «1 подкатегория», «4 подкатегории», «11 подкатегорий». */
function plural(count: number, forms: Forms): string {
  return `${count} ${forms[pluralIndex(count)]}`
}

const SUBCATEGORIES: Forms = ['подкатегория', 'подкатегории', 'подкатегорий']
const OPERATIONS: Forms = ['операция', 'операции', 'операций']
// Глагол согласуется с числом так же, как существительное: «исчезнет 1», «исчезнут 3»
const WILL_VANISH: Forms = ['исчезнет', 'исчезнут', 'исчезнут']

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

  // Здесь, в отличие от остальных экранов, нужны и скрытые категории: иначе спрятать
  // категорию можно, а вернуть — уже нет, и «скрыть» становится необратимым
  const categories = useQuery({
    queryKey: ['categories', 'manage'],
    queryFn: () => api.categories(undefined, true),
  })

  const visible = useMemo(
    () => (categories.data ?? []).filter((item) => item.kind === kind && !item.archived),
    [categories.data, kind],
  )
  const archived = useMemo(
    () => (categories.data ?? []).filter((item) => item.kind === kind && item.archived),
    [categories.data, kind],
  )
  const tree = useMemo(() => buildTree(visible), [visible])

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

  // --- удаление ---
  const [removing, setRemoving] = useState<Category | null>(null)
  const [replacement, setReplacement] = useState('')
  const [replacementName, setReplacementName] = useState('')

  const usage = useQuery({
    queryKey: ['category-usage', removing?.id],
    queryFn: () => api.categoryUsage(removing!.id),
    enabled: removing !== null,
  })

  const startRemoving = (category: Category) => {
    haptic()
    setForm(null)
    setRemoving(category)
    setReplacement('')
    setReplacementName('')
  }

  const closeRemoving = () => {
    setRemoving(null)
    remove.reset()
  }

  const hide = useMutation({
    mutationFn: (category: Category) => api.updateCategory(category.id, { archived: true }),
    onSuccess: () => {
      notify('success')
      onDone('Категория скрыта — история осталась как была')
      closeRemoving()
      refresh()
    },
    onError: () => notify('error'),
  })

  const unhide = useMutation({
    mutationFn: (category: Category) => api.updateCategory(category.id, { archived: false }),
    onSuccess: () => {
      notify('success')
      onDone('Категория снова в списках')
      refresh()
    },
    onError: () => notify('error'),
  })

  const remove = useMutation({
    mutationFn: async (category: Category) => {
      // Новую категорию заводим тем же нажатием: иначе человеку пришлось бы выйти,
      // создать её руками и вернуться к удалению — три экрана вместо одного
      let target: string | null = replacement || null
      if (replacement === NEW_CATEGORY) {
        const created = await api.createCategory({
          name: replacementName.trim(),
          kind: category.kind,
        })
        target = created.id
      }
      return api.deleteCategory(category.id, target)
    },
    onSuccess: (result) => {
      notify('success')
      onDone(
        result.moved > 0
          ? `Удалено, операций перенесено: ${result.moved}`
          : 'Категория удалена',
      )
      closeRemoving()
      refresh()
    },
    onError: () => notify('error'),
  })

  /**
   * Куда можно перенести: тот же тип, кроме самой категории и её подкатегорий.
   * Порядок — как в дереве: родитель, сразу под ним его дети. Плоский список,
   * отсортированный сервером, ставит «Кафе · Кофе» выше самих «Кафе», и выбирать
   * в таком списке неудобно.
   */
  const replacements = useMemo(() => {
    if (!removing) return []
    const all = categories.data ?? []
    const byId = indexById(all)
    const doomed = new Set([removing.id])
    for (const item of all) {
      if (item.parent_id === removing.id) doomed.add(item.id)
    }
    const suitable = (item: Category) =>
      item.kind === removing.kind && !doomed.has(item.id) && !item.archived

    return buildTree(all.filter((item) => item.kind === removing.kind))
      .flatMap(({ category, children }) => [category, ...children])
      .filter(suitable)
      .map((item) => ({ id: item.id, label: fullName(item, byId) }))
  }, [categories.data, removing])

  const needsReplacement = usage.data?.needs_replacement ?? false
  const replacementReady =
    !needsReplacement ||
    (replacement !== '' &&
      (replacement !== NEW_CATEGORY || replacementName.trim().length > 0))

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

      <ErrorNote
        error={categories.error ?? save.error ?? hide.error ?? unhide.error ?? remove.error}
      />

      {removing && (
        <div className="card">
          <p className="section-title" style={{ margin: '0 0 10px' }}>
            Удалить «{removing.name}»?
          </p>

          {usage.isPending && <p className="hint">Считаем, что зацепит…</p>}

          {usage.data && (
            <>
              <p className="hint" style={{ marginTop: 0 }}>
                {usage.data.transactions > 0
                  ? `На категории ${plural(usage.data.transactions, OPERATIONS)}. ` +
                    'Они не пропадут — выберите, куда их перенести.'
                  : 'Операций на ней нет, удаление ничего не заденет.'}
                {usage.data.children > 0 &&
                  ` Вместе с ней ${WILL_VANISH[pluralIndex(usage.data.children)]} ` +
                    `${plural(usage.data.children, SUBCATEGORIES)}.`}
              </p>

              {needsReplacement && (
                <>
                  <select
                    className="field"
                    value={replacement}
                    onChange={(event) => setReplacement(event.target.value)}
                    aria-label="Куда перенести операции"
                  >
                    <option value="">Куда перенести операции…</option>
                    {replacements.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.label}
                      </option>
                    ))}
                    <option value={NEW_CATEGORY}>＋ В новую категорию</option>
                  </select>

                  {replacement === NEW_CATEGORY && (
                    <input
                      className="field"
                      style={{ marginTop: 8 }}
                      value={replacementName}
                      maxLength={64}
                      placeholder="Название новой категории"
                      autoFocus
                      onChange={(event) => setReplacementName(event.target.value)}
                      aria-label="Название новой категории"
                    />
                  )}
                </>
              )}

              <div className="sheet__actions">
                <button className="btn btn--ghost" type="button" onClick={closeRemoving}>
                  Отмена
                </button>
                <button
                  className="btn btn--destructive"
                  type="button"
                  disabled={!replacementReady || remove.isPending}
                  onClick={() => remove.mutate(removing)}
                >
                  {remove.isPending ? 'Удаляем…' : 'Удалить'}
                </button>
              </div>

              {usage.data.transactions > 0 && (
                <p className="hint" style={{ marginBottom: 0 }}>
                  Если история за прошлые месяцы должна остаться как есть — категорию
                  лучше не удалять, а спрятать: она исчезнет из списков выбора, а отчёты
                  не изменятся.{' '}
                  <button
                    className="btn btn--link"
                    type="button"
                    disabled={hide.isPending}
                    onClick={() => hide.mutate(removing)}
                  >
                    Спрятать
                  </button>
                </p>
              )}
            </>
          )}
        </div>
      )}

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
                {children.length > 0
                  ? plural(children.length, SUBCATEGORIES)
                  : 'без подкатегорий'}
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
                title="Удалить"
                onClick={() => startRemoving(category)}
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
                  title="Удалить"
                  onClick={() => startRemoving(child)}
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

      {archived.length > 0 && (
        <>
          <p className="section-title">Скрытые</p>
          <div className="card card--tight">
            {archived.map((category) => (
              <div className="row" key={category.id}>
                <div className="row__icon">{category.icon || '•'}</div>
                <div className="row__body">
                  <div className="row__title">{category.name}</div>
                  <div className="row__sub">не показывается при выборе</div>
                </div>
                <div className="row__tools">
                  <button
                    type="button"
                    className="icon-btn"
                    title="Вернуть в списки"
                    disabled={unhide.isPending}
                    onClick={() => unhide.mutate(category)}
                  >
                    ↩️
                  </button>
                  <button
                    type="button"
                    className="icon-btn"
                    title="Удалить"
                    onClick={() => startRemoving(category)}
                  >
                    🗑
                  </button>
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      <p className="hint">
        Категорию, на которую уже ссылаются операции, удалить нельзя — она скрывается
        из списков, а история за прошлые месяцы остаётся разбитой как была.
      </p>
    </div>
  )
}
