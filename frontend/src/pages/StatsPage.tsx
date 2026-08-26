import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'

import { api } from '../api'
import { indexById } from '../categories'
import CategoryFilterSheet from '../components/CategoryFilterSheet'
import Disclosure from '../components/Disclosure'
import ErrorNote from '../components/ErrorNote'
import PeriodPicker from '../components/PeriodPicker'
import ReportTotals from '../components/ReportTotals'
import TrendChart from '../components/TrendChart'
import { formatDay, formatMoney, percentDelta } from '../format'
import { DEFAULT_RANGE, type Range, formatRange, rangeKey } from '../period'
import { useSticky } from '../sticky'
import { haptic, notify } from '../telegram'
import type { CategoryTotal, Filters } from '../types'

interface Props {
  currentUserId: string
  /** Провал в Историю: те же период и категория, что в строке отчёта. */
  onDrillDown: (range: Range, filters: Filters) => void
  onDone: (message: string) => void
}

/** Что человек оставил открытым в прошлый раз. Всё это переживает закрытие приложения. */
interface Saved {
  range: Range
  personId: string | null
  accountId: string | null
  excluded: string[]
  excludeUncategorized: boolean
  excludedTags: string[]
}

const EMPTY: Saved = {
  range: DEFAULT_RANGE,
  personId: null,
  accountId: null,
  excluded: [],
  excludeUncategorized: false,
  excludedTags: [],
}

/** Динамику всегда смотрим за год: график из одного столбика ничего не сравнивает. */
const TREND_RANGE: Range = { kind: 'preset', preset: 'year' }

export default function StatsPage({ currentUserId, onDrillDown, onDone }: Props) {
  const queryClient = useQueryClient()
  const [saved, setSaved] = useSticky<Saved>('report', currentUserId, EMPTY)
  const [side, setSide] = useState<'expense' | 'income'>('expense')
  const [byShares, setByShares] = useState(false)
  const [filterOpen, setFilterOpen] = useState(false)
  const [trendOpen, setTrendOpen] = useState(false)

  const patch = (next: Partial<Saved>) => {
    haptic()
    setSaved((current) => ({ ...current, ...next }))
  }

  const filters: Filters = useMemo(
    () => ({
      personId: saved.personId,
      accountId: saved.accountId,
      excludeCategoryIds: saved.excluded,
      excludeUncategorized: saved.excludeUncategorized,
      excludeTags: saved.excludedTags,
    }),
    [saved],
  )

  const users = useQuery({ queryKey: ['users'], queryFn: api.users })
  const accounts = useQuery({ queryKey: ['accounts'], queryFn: api.accounts })
  const categories = useQuery({
    // Скрытые тоже: прошлогодний отчёт может целиком стоять на спрятанной категории,
    // и не дать её исключить значило бы запереть фильтр
    queryKey: ['categories', 'manage'],
    queryFn: () => api.categories(undefined, true),
  })
  const tags = useQuery({ queryKey: ['tags'], queryFn: api.tags })
  const views = useQuery({ queryKey: ['report-views'], queryFn: api.reportViews })

  const summary = useQuery({
    queryKey: ['summary', rangeKey(saved.range), filters],
    queryFn: () => api.summary(saved.range, filters, true),
  })
  const trend = useQuery({
    queryKey: ['trend', filters],
    queryFn: () => api.trend(TREND_RANGE, filters),
    enabled: trendOpen,
  })

  const share = useMutation({
    mutationFn: () => api.shareReport(saved.range, filters),
    onSuccess: () => {
      notify('success')
      onDone('Сводка ушла в чат с ботом')
    },
    onError: (error) => {
      notify('error')
      onDone((error as Error).message)
    },
  })

  const copyForLlm = useMutation({
    mutationFn: async () => {
      const dump = await api.llmExport(saved.range, filters)
      await navigator.clipboard.writeText(dump)
    },
    onSuccess: () => {
      notify('success')
      onDone('Выгрузка скопирована — вставьте её в чат с нейросетью')
    },
    onError: () => onDone('Не удалось скопировать — буфер обмена недоступен'),
  })

  const saveView = useMutation({
    mutationFn: (name: string) => api.saveReportView(name, saved as unknown as Record<string, unknown>),
    onSuccess: (view) => {
      notify('success')
      onDone(`Вид «${view.name}» сохранён`)
      queryClient.invalidateQueries({ queryKey: ['report-views'] })
    },
    onError: (error) => onDone((error as Error).message),
  })

  const dropView = useMutation({
    mutationFn: (id: string) => api.dropReportView(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['report-views'] }),
  })

  const data = summary.data
  const catalog = useMemo(() => indexById(categories.data ?? []), [categories.data])
  const rows = data ? (side === 'expense' ? data.by_category : data.by_income_category) : []
  const people = byShares ? data?.by_spender ?? [] : data?.by_person ?? []
  const hiddenCount = saved.excluded.length + saved.excludedTags.length +
    (saved.excludeUncategorized ? 1 : 0)
  const pickedAccount = (accounts.data ?? []).find((account) => account.id === saved.accountId)

  const resetExclusions = () =>
    patch({ excluded: [], excludeUncategorized: false, excludedTags: [] })

  const drill = (item: CategoryTotal) => {
    if (!item.category_id) return
    haptic()
    onDrillDown(saved.range, { categoryId: item.category_id })
  }

  const promptView = () => {
    const name = window.prompt('Название вида — «Быт», «Без ипотеки»')?.trim()
    if (name) saveView.mutate(name)
  }

  return (
    <div className="page">
      <PeriodPicker
        value={saved.range}
        onChange={(range) => patch({ range })}
        label={data ? formatRange(data.period_start, data.period_end) : undefined}
      />

      {/* Сохранённые виды: набор фильтров одним касанием вместо десяти галочек */}
      {(views.data?.length ?? 0) > 0 && (
        <div className="chips">
          {(views.data ?? []).map((view) => (
            <button
              key={view.id}
              type="button"
              className="chip chip--ghost"
              onClick={() => {
                haptic()
                setSaved({ ...EMPTY, ...(view.payload as unknown as Saved) })
              }}
              onDoubleClick={() => dropView.mutate(view.id)}
              title="Двойное касание — удалить вид"
            >
              {view.name}
            </button>
          ))}
        </div>
      )}

      {/* Отчёт по одному человеку: те же цифры, но только по его тратам. Его —
          значит записанным на его счёт, кто бы их ни вносил */}
      {(users.data?.length ?? 0) > 1 && (
        <div className="chips">
          <button
            type="button"
            className="chip"
            data-active={!saved.personId}
            onClick={() => patch({ personId: null })}
          >
            Вместе
          </button>
          {(users.data ?? []).map((user) => (
            <button
              key={user.id}
              type="button"
              className="chip"
              data-active={saved.personId === user.id}
              onClick={() => patch({ personId: saved.personId === user.id ? null : user.id })}
            >
              {user.id === currentUserId ? 'Я' : user.display_name}
            </button>
          ))}
        </div>
      )}

      {/* Счета: «только общий» — второй по частоте вопрос после «только мои траты».
          Но спрашивают его редко, а ряд из четырёх чипсов стоял выше первой цифры
          и отодвигал отчёт за нижний край экрана. Свёрнутой строкой видно и текущий
          выбор, и то, что это вообще фильтр, а не разбивка */}
      {(accounts.data?.length ?? 0) > 1 && (
        <Disclosure
          title="Кошелёк"
          summary={pickedAccount?.name ?? 'Все счета'}
          defaultOpen={Boolean(saved.accountId)}
        >
          <div className="chips">
            <button
              type="button"
              className="chip chip--ghost"
              data-active={!saved.accountId}
              onClick={() => patch({ accountId: null })}
            >
              Все счета
            </button>
            {(accounts.data ?? []).map((account) => (
              <button
                key={account.id}
                type="button"
                className="chip chip--ghost"
                data-active={saved.accountId === account.id}
                onClick={() =>
                  patch({ accountId: saved.accountId === account.id ? null : account.id })
                }
              >
                {account.is_shared ? '👥' : '👤'} {account.name}
              </button>
            ))}
          </div>
          <p className="hint" style={{ margin: 0 }}>
            Отчёт по одному кошельку: только те операции, что записаны на этот счёт.
            «Общий» покажет траты из общего кошелька, личный — то, что человек платил
            своими.
          </p>
        </Disclosure>
      )}

      <div className="chips">
        <button
          type="button"
          className="chip chip--ghost"
          data-active={hiddenCount > 0}
          onClick={() => {
            haptic()
            setFilterOpen(true)
          }}
        >
          🚫 {hiddenCount > 0 ? `Скрыто: ${hiddenCount}` : 'Что не показывать'}
        </button>
        {hiddenCount > 0 && (
          <button type="button" className="chip chip--ghost" onClick={resetExclusions}>
            Сбросить
          </button>
        )}
      </div>

      <ErrorNote error={summary.error} />

      {data && <ReportTotals data={data} onResetExclusions={resetExclusions} />}

      {data && data.income_minor > 0 && data.by_income_category.length > 0 && (
        <div className="segmented">
          {(['expense', 'income'] as const).map((value) => (
            <button
              key={value}
              type="button"
              data-active={side === value}
              onClick={() => {
                haptic()
                setSide(value)
              }}
            >
              {value === 'expense' ? 'Расходы' : 'Доходы'}
            </button>
          ))}
        </div>
      )}

      {rows.length > 0 && (
        <>
          <p className="section-title">
            {side === 'expense' ? 'Куда ушли деньги' : 'Откуда пришли деньги'}
          </p>
          <div className="card card--tight">
            {rows.map((item) => (
              <CategoryRow
                key={`${item.parent_id ?? 'root'}:${item.category_id ?? 'none'}`}
                item={item}
                onDrill={() => drill(item)}
              />
            ))}
          </div>
        </>
      )}

      {data && data.largest.length > 0 && side === 'expense' && (
        <>
          <p className="section-title">Самые крупные</p>
          <div className="card card--tight">
            {data.largest.map((tx) => {
              const category = tx.category_id ? catalog.get(tx.category_id) : undefined
              return (
                <div className="row" key={tx.id}>
                  <div className="row__icon">{category?.icon || '•'}</div>
                  <div className="row__body">
                    <div className="row__title">{category?.name ?? 'Без категории'}</div>
                    <div className="row__sub">
                      {formatDay(tx.occurred_at)}
                      {tx.note ? ` · ${tx.note}` : ''}
                    </div>
                  </div>
                  <div className="row__amount">{formatMoney(tx.amount_minor)}</div>
                </div>
              )
            })}
          </div>
        </>
      )}

      {data && data.repeated.length > 0 && side === 'expense' && (
        <>
          <p className="section-title">Повторяется</p>
          <div className="card card--tight">
            {data.repeated.map((item) => (
              <div className="row" key={item.note}>
                <div className="row__icon">🔁</div>
                <div className="row__body">
                  <div className="row__title">{item.note}</div>
                  <div className="row__sub">{item.count} раза за период</div>
                </div>
                <div className="row__amount">{formatMoney(item.total_minor)}</div>
              </div>
            ))}
          </div>
          <p className="hint">
            Одинаковые комментарии за период. Обычно это подписки — их проще всего
            и отменить.
          </p>
        </>
      )}

      {data && !saved.personId && people.length > 1 && (
        <>
          <p className="section-title section-title--row">
            <span>Кто сколько</span>
            <button
              className="btn btn--link"
              type="button"
              onClick={() => {
                haptic()
                setByShares((current) => !current)
              }}
            >
              {byShares ? 'по счёту' : 'по долям'}
            </button>
          </p>
          <div className="card card--tight">
            {people.map((item) => (
              <div className="row row--tappable" key={item.user_id}>
                <div className="row__icon">👤</div>
                <div className="row__body">
                  <div className="row__title">
                    {item.name}
                    {item.user_id === currentUserId ? ' (вы)' : ''}
                  </div>
                </div>
                <button
                  type="button"
                  className="btn btn--ghost btn--slim"
                  onClick={() => patch({ personId: item.user_id })}
                >
                  {formatMoney(item.amount_minor)}
                </button>
              </div>
            ))}
          </div>
          <p className="hint">
            {byShares
              ? 'По долям: трата с общего счёта поделена пополам. Кто кому должен — на вкладке «Ещё».'
              : 'По счёту: с чьего счёта ушли деньги. У общего счёта владельца нет, и трата числится за тем, кто её записал — переключите «по долям».'}
          </p>
        </>
      )}

      <p className="section-title section-title--row">
        <span>Динамика по месяцам</span>
        <button
          className="btn btn--link"
          type="button"
          onClick={() => {
            haptic()
            setTrendOpen((current) => !current)
          }}
        >
          {trendOpen ? 'скрыть' : 'показать'}
        </button>
      </p>
      {trendOpen && (
        <>
          <ErrorNote error={trend.error} />
          {trend.isPending && <p className="hint">Загружаем…</p>}
          {trend.data && <TrendChart trend={trend.data} />}
        </>
      )}

      {data && data.count === 0 && (
        <p className="hint" style={{ textAlign: 'center' }}>
          За этот период данных нет
        </p>
      )}

      {/* Три действия в строку. Подписи короткие намеренно: на 390 точках ширины
          «Для нейросети» переносится на вторую строку и ломает ряд */}
      <div className="icon-row">
        <button
          className="btn btn--ghost btn--compact"
          type="button"
          disabled={share.isPending}
          onClick={() => share.mutate()}
        >
          {share.isPending ? 'Отправляем…' : '💬 В чат'}
        </button>
        <button
          className="btn btn--ghost btn--compact"
          type="button"
          disabled={copyForLlm.isPending}
          onClick={() => copyForLlm.mutate()}
        >
          🤖 Нейросети
        </button>
        <button className="btn btn--ghost btn--compact" type="button" onClick={promptView}>
          ⭐️ Вид
        </button>
      </div>

      {filterOpen && (
        <CategoryFilterSheet
          categories={(categories.data ?? []).filter((item) => item.kind === side)}
          totals={rows}
          tags={tags.data ?? []}
          excluded={saved.excluded}
          excludeUncategorized={saved.excludeUncategorized}
          excludedTags={saved.excludedTags}
          onClose={() => setFilterOpen(false)}
          onApply={(next) => {
            patch({
              excluded: next.excluded,
              excludeUncategorized: next.excludeUncategorized,
              excludedTags: next.excludedTags,
            })
            setFilterOpen(false)
          }}
        />
      )}
    </div>
  )
}

/**
 * Строка категории.
 *
 * Полоса значит одно из двух и подписана соответственно: если у категории есть
 * месячный лимит — это «сколько от лимита истрачено», и она краснеет на переборе;
 * если лимита нет — обычная доля в расходах периода.
 */
function CategoryRow({ item, onDrill }: { item: CategoryTotal; onDrill: () => void }) {
  const limited = item.limit_minor > 0
  const ratio = limited ? item.amount_minor / item.limit_minor : item.share
  const over = limited && item.amount_minor > item.limit_minor
  const delta = item.previous_minor ? percentDelta(item.amount_minor, item.previous_minor) : null

  return (
    <div
      className={`row row--tappable${item.parent_id ? ' row--nested' : ''}`}
      onClick={onDrill}
      role="button"
      tabIndex={0}
      onKeyDown={(event) => event.key === 'Enter' && onDrill()}
    >
      <div className={`row__icon${item.parent_id ? ' row__icon--small' : ''}`}>
        {item.icon || '•'}
      </div>
      <div className="row__body">
        <div className="row__title">{item.name}</div>
        {/* Полоса нагляднее процента: соотношение видно, не читая цифр */}
        <div className="bar">
          <i
            style={{ width: `${Math.min(100, Math.max(2, Math.round(ratio * 100)))}%` }}
            data-over={over}
          />
        </div>
        {limited && (
          <div className="row__sub">
            {over ? 'перебор ' : 'из '}
            {formatMoney(item.limit_minor)}
          </div>
        )}
      </div>
      <div className="row__amount">
        {formatMoney(item.amount_minor)}
        <div className="row__sub" style={{ textAlign: 'right' }}>
          {delta ?? `${Math.round(item.share * 100)}%`}
        </div>
      </div>
    </div>
  )
}
