import { getInitData } from './telegram'
import type {
  Account,
  Balances,
  Category,
  LoginResponse,
  Period,
  Settlement,
  Summary,
  SyncStatus,
  Transaction,
  TransactionPage,
  TransactionType,
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
    body: JSON.stringify({ init_data: getInitData() }),
  })
  token = result.token
  return result
}

export const api = {
  accounts: () => request<Account[]>('/accounts'),
  categories: (kind?: string) =>
    request<Category[]>(`/categories${kind ? `?kind=${kind}` : ''}`),
  recentCategories: () => request<string[]>('/categories/recent'),
  users: () => request<{ id: string; display_name: string }[]>('/users'),

  transactions: (period: Period, limit = 50, offset = 0) =>
    request<TransactionPage>(
      `/transactions?period=${period}&limit=${limit}&offset=${offset}`,
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

  deleteTransaction: (id: string) =>
    request<void>(`/transactions/${id}`, { method: 'DELETE' }),

  summary: (period: Period) => request<Summary>(`/stats/summary?period=${period}`),
  balances: () => request<Balances>('/stats/balances'),
  settle: () => request<Settlement>('/stats/settle'),

  syncStatus: () => request<SyncStatus>('/sync/status'),
  syncPush: () => request<{ updated: number; appended: number }>('/sync/push', { method: 'POST' }),
  syncPull: () =>
    request<{ applied: number; created: number; skipped: number }>('/sync/pull', {
      method: 'POST',
    }),
}
