import { getInitData, getTimezone } from './telegram'
import type {
  Account,
  Balances,
  Category,
  CategoryDeleted,
  CategoryKind,
  CategoryUsage,
  Filters,
  LoginResponse,
  Period,
  Reminder,
  Settlement,
  Summary,
  SyncStatus,
  Transaction,
  TransactionPage,
  TransactionType,
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

/** Собирает query-строку, пропуская пустые фильтры. */
function query(params: Record<string, string | number | null | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== '') {
      search.set(key, String(value))
    }
  }
  return search.toString()
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

  transactions: (period: Period, filters: Filters = {}, limit = 50, offset = 0) =>
    request<TransactionPage>(
      `/transactions?${query({
        period,
        limit,
        offset,
        author_ids: filters.authorId,
        category_ids: filters.categoryId,
        types: filters.type,
        search: filters.search,
      })}`,
    ),

  createTransaction: (payload: {
    type: TransactionType
    amount: string
    category_id?: string | null
    account_id?: string | null
    counter_account_id?: string | null
    note?: string
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
      occurred_at?: string
    },
  ) =>
    request<Transaction>(`/transactions/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),

  deleteTransaction: (id: string) =>
    request<void>(`/transactions/${id}`, { method: 'DELETE' }),

  summary: (period: Period, filters: Filters = {}) =>
    request<Summary>(
      `/stats/summary?${query({
        period,
        author_ids: filters.authorId,
        category_ids: filters.categoryId,
      })}`,
    ),
  balances: () => request<Balances>('/stats/balances'),
  settle: () => request<Settlement>('/stats/settle'),

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
