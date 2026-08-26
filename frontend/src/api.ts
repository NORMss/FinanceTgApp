import { type Range, rangeQuery } from './period'
import { getInitData, getTimezone } from './telegram'
import type {
  Account,
  Balances,
  Budget,
  Category,
  CategoryDeleted,
  CategoryKind,
  CategoryUsage,
  Filters,
  LoginResponse,
  Reminder,
  ReportView,
  Settlement,
  Summary,
  SyncStatus,
  Tag,
  Transaction,
  TransactionPage,
  TransactionType,
  Trend,
  User,
} from './types'

const BASE = '/api'

let token: string | null = null

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...init.headers,
      },
    })
  } catch (cause) {
    // fetch бросает голый TypeError и на обрыв сети, и на упавший прокси, и на CORS.
    // Превращаем в ApiError со статусом 0, чтобы наверху был один тип ошибки.
    throw new ApiError(
      `Сервер не ответил (${cause instanceof Error ? cause.message : 'нет связи'})`,
      0,
    )
  }

  if (!response.ok) {
    // FastAPI кладёт человекочитаемое сообщение в detail — показываем его как есть
    const detail = await response
      .json()
      .then((body) => body?.detail)
      .catch(() => null)
    throw new ApiError(detail ?? `Ошибка ${response.status}`, response.status)
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

/** То же самое, но ответ читается текстом: выгрузка для нейросети — markdown, не JSON. */
async function requestText(path: string): Promise<string> {
  const response = await fetch(`${BASE}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  }).catch(() => {
    throw new ApiError('Сервер не ответил', 0)
  })
  if (!response.ok) throw new ApiError(`Ошибка ${response.status}`, response.status)
  return response.text()
}

export async function login(): Promise<LoginResponse> {
  const result = await request<LoginResponse>('/auth/login', {
    method: 'POST',
    // Пояс отправляем при каждом входе: человек переехал или улетел — напоминание
    // должно ехать за ним, а не остаться в поясе первого запуска
    body: JSON.stringify({ init_data: getInitData(), tz: getTimezone() }),
  })
  token = result.token
  return result
}

type QueryValue = string | number | boolean | string[] | null | undefined

/**
 * Собирает query-строку, пропуская пустые фильтры.
 *
 * Массив разворачивается в повторяющийся ключ (`ids=a&ids=b`), а не склеивается через
 * запятую: FastAPI разбирает `list[str]` именно так, и «a,b» приехал бы одним
 * идентификатором — фильтр молча не сработал бы ни на одной операции.
 */
function query(params: Record<string, QueryValue>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (Array.isArray(value)) {
      for (const item of value) if (item) search.append(key, item)
    } else if (typeof value === 'boolean') {
      if (value) search.set(key, 'true')
    } else if (value !== null && value !== undefined && value !== '') {
      search.set(key, String(value))
    }
  }
  return search.toString()
}

/** Общая часть query-строки отчёта, истории и выгрузки — один разбор на всех. */
function filterQuery(filters: Filters): Record<string, QueryValue> {
  return {
    author_ids: filters.authorId,
    category_ids: filters.categoryId,
    account_ids: filters.accountId,
    search: filters.search,
    exclude_category_ids: filters.excludeCategoryIds,
    exclude_uncategorized: filters.excludeUncategorized,
    tags: filters.tags,
    exclude_tags: filters.excludeTags,
  }
}

export const api = {
  accounts: () => request<Account[]>('/accounts'),
  categories: (kind?: string, includeArchived = false) =>
    request<Category[]>(
      `/categories?${query({ kind, include_archived: includeArchived ? 'true' : '' })}`,
    ),
  recentCategories: () => request<string[]>('/categories/recent'),
  users: () => request<User[]>('/users'),

  createCategory: (payload: {
    name: string
    kind?: CategoryKind
    icon?: string
    parent_id?: string | null
  }) =>
    request<Category>('/categories', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  updateCategory: (
    id: string,
    // parent_id: null — «поднять на верхний уровень», поэтому именно undefined,
    // а не null означает «не трогать родителя»
    payload: { name?: string; icon?: string; parent_id?: string | null; archived?: boolean },
  ) =>
    request<Category>(`/categories/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),

  categoryUsage: (id: string) => request<CategoryUsage>(`/categories/${id}/usage`),

  // moveTo обязателен, когда на категории висят операции: сервер откажет с 409,
  // а операции без категории испортили бы отчёт за прошлые месяцы
  deleteCategory: (id: string, moveTo?: string | null) =>
    request<CategoryDeleted>(
      `/categories/${id}${moveTo ? `?move_to=${encodeURIComponent(moveTo)}` : ''}`,
      { method: 'DELETE' },
    ),

  createAccount: (payload: { name: string; is_shared?: boolean }) =>
    request<Account>('/accounts', { method: 'POST', body: JSON.stringify(payload) }),

  transactions: (range: Range, filters: Filters = {}, limit = 50, offset = 0) =>
    request<TransactionPage>(
      `/transactions?${query({
        ...rangeQuery(range),
        ...filterQuery(filters),
        limit,
        offset,
        types: filters.type,
      })}`,
    ),

  createTransaction: (payload: {
    type: TransactionType
    amount: string
    category_id?: string | null
    account_id?: string | null
    counter_account_id?: string | null
    note?: string
    tags?: string
    occurred_at?: string
    split_mode?: 'auto' | 'none'
  }) =>
    request<Transaction>('/transactions', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  updateTransaction: (
    id: string,
    payload: {
      type?: TransactionType
      amount?: string
      category_id?: string | null
      account_id?: string
      note?: string
      tags?: string
      occurred_at?: string
    },
  ) =>
    request<Transaction>(`/transactions/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),

  deleteTransaction: (id: string) =>
    request<void>(`/transactions/${id}`, { method: 'DELETE' }),

  summary: (range: Range, filters: Filters = {}, compare = false) =>
    request<Summary>(
      `/stats/summary?${query({ ...rangeQuery(range), ...filterQuery(filters), compare })}`,
    ),
  trend: (range: Range, filters: Filters = {}) =>
    request<Trend>(`/stats/trend?${query({ ...rangeQuery(range), ...filterQuery(filters) })}`),
  shareReport: (range: Range, filters: Filters = {}) =>
    request<{ sent: boolean }>(
      `/stats/share?${query({ ...rangeQuery(range), ...filterQuery(filters) })}`,
      { method: 'POST' },
    ),
  balances: () => request<Balances>('/stats/balances'),
  settle: () => request<Settlement>('/stats/settle'),

  budgets: () => request<Budget[]>('/budgets'),
  setBudget: (categoryId: string, limit: string) =>
    request<Budget>(`/budgets/${categoryId}`, {
      method: 'PUT',
      body: JSON.stringify({ limit }),
    }),
  dropBudget: (categoryId: string) =>
    request<void>(`/budgets/${categoryId}`, { method: 'DELETE' }),

  reportViews: () => request<ReportView[]>('/report-views'),
  saveReportView: (name: string, payload: Record<string, unknown>) =>
    request<ReportView>('/report-views', {
      method: 'POST',
      body: JSON.stringify({ name, payload }),
    }),
  dropReportView: (id: string) => request<void>(`/report-views/${id}`, { method: 'DELETE' }),

  tags: () => request<Tag[]>('/tags'),

  /**
   * Выгрузка для нейросети — markdown-текстом, чтобы положить его в буфер обмена.
   *
   * Не ссылкой: токен ходит заголовком, и по голому адресу пришёл бы 401. Скачивание
   * файла внутри Telegram тоже ненадёжно, а текст вставляется в чат с моделью как есть.
   */
  llmExport: (range: Range, filters: Filters = {}) =>
    requestText(`/export/llm?${query({ ...rangeQuery(range), ...filterQuery(filters) })}`),

  reminder: () => request<Reminder>('/me/reminder'),
  saveReminder: (payload: { enabled?: boolean; time?: string; tz?: string }) =>
    request<Reminder>('/me/reminder', { method: 'PUT', body: JSON.stringify(payload) }),

  syncStatus: () => request<SyncStatus>('/sync/status'),
  syncPush: () => request<{ updated: number; appended: number }>('/sync/push', { method: 'POST' }),
  syncPull: () =>
    request<{ applied: number; created: number; skipped: number }>('/sync/pull', {
      method: 'POST',
    }),
}
