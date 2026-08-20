export type TransactionType = 'expense' | 'income' | 'transfer'
export type CategoryKind = 'expense' | 'income'

export interface User {
  id: string
  telegram_id: number
  display_name: string
  username: string | null
}

export interface LoginResponse {
  token: string
  expires_at: number
  user: User
  base_currency: string
}

export interface Account {
  id: string
  name: string
  kind: string
  currency: string
  is_shared: boolean
  owner_id: string | null
  archived: boolean
  sort: number
}

export interface Category {
  id: string
  name: string
  kind: CategoryKind
  icon: string
  parent_id: string | null
  archived: boolean
  sort: number
}

/** Во что обойдётся удаление категории — спрашивается до того, как показать кнопку. */
export interface CategoryUsage {
  transactions: number
  children: number
  rules: number
  /** true — операции придётся перенести в другую категорию, иначе сервер откажет. */
  needs_replacement: boolean
}

export interface CategoryDeleted {
  result: 'deleted'
  moved: number
  removed: number
}

export interface Transaction {
  id: string
  occurred_at: string
  type: TransactionType
  amount_minor: number
  currency: string
  account_id: string
  counter_account_id: string | null
  category_id: string | null
  author_id: string
  note: string
  tags: string
  source: string
  splits: { user_id: string; share_minor: number }[]
}

export interface TransactionPage {
  items: Transaction[]
  total: number
  limit: number
  offset: number
}

export interface CategoryTotal {
  category_id: string | null
  name: string
  icon: string
  /** Вместе с подкатегориями. own_minor — то, что записано прямо на эту категорию. */
  amount_minor: number
  count: number
  share: number
  parent_id: string | null
  own_minor: number
}

/** Фильтры истории и отчёта. Пустые поля в запрос не уходят. */
export interface Filters {
  /** Чья это трата: владелец счёта, а у общего счёта — тот, кто записал. */
  personId?: string | null
  categoryId?: string | null
  type?: TransactionType | null
  search?: string
}

export interface Summary {
  period_start: string
  period_end: string
  income_minor: number
  expense_minor: number
  net_minor: number
  count: number
  by_category: CategoryTotal[]
  by_person: { user_id: string; name: string; amount_minor: number }[]
}

export interface Balances {
  accounts: {
    account_id: string
    name: string
    currency: string
    is_shared: boolean
    balance_minor: number
  }[]
  total_minor: number
}

export interface Settlement {
  users: {
    user_id: string
    name: string
    paid_minor: number
    owed_minor: number
    net_minor: number
  }[]
  hint: string
}

export interface Reminder {
  enabled: boolean
  /** «21:00» — в этом же виде значение уходит в <input type="time">. */
  time: string
  tz: string
  /** false, когда бот выключен: настройка есть, но присылать напоминание некому. */
  delivery_ready: boolean
}

export interface SyncStatus {
  enabled: boolean
  configured: boolean
  pending: number
  last_push_at: string | null
  last_error: string | null
  spreadsheet_url: string | null
}

export type Period = 'week' | 'month' | 'prev_month' | '30d' | 'year' | 'all'
