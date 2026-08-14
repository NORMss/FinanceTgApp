import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../api'
import CategoryPicker from '../components/CategoryPicker'
import { formatMoney, isValidAmount, normalizeAmountInput } from '../format'
import { haptic, notify } from '../telegram'
import type { TransactionType } from '../types'

interface Props {
  onDone: (message: string) => void
}

/**
 * Главный экран: добавить трату за три касания.
 * Категории отсортированы так, что последние использованные стоят первыми — на практике
 * именно они закрывают почти весь ежедневный ввод.
 */
export default function AddPage({ onDone }: Props) {
  const queryClient = useQueryClient()
  const [type, setType] = useState<TransactionType>('expense')
  const [amount, setAmount] = useState('')
  const [categoryId, setCategoryId] = useState<string | null>(null)
  const [note, setNote] = useState('')
  const [accountId, setAccountId] = useState<string | null>(null)

  const kind = type === 'income' ? 'income' : 'expense'
  const categories = useQuery({ queryKey: ['categories', kind], queryFn: () => api.categories(kind) })
  const recent = useQuery({ queryKey: ['recent-categories'], queryFn: api.recentCategories })
  const accounts = useQuery({ queryKey: ['accounts'], queryFn: api.accounts })

  const create = useMutation({
    mutationFn: () =>
      api.createTransaction({
        type,
        amount: normalizeAmountInput(amount),
        category_id: categoryId,
        account_id: accountId,
        note: note.trim(),
      }),
    onSuccess: (tx) => {
      notify('success')
      onDone(
        `${type === 'income' ? 'Доход' : 'Расход'} ${formatMoney(tx.amount_minor)} записан`,
      )
      setAmount('')
      setNote('')
      // Сумма меняет всё: список, сводку, остатки и взаиморасчёты
      queryClient.invalidateQueries()
    },
    onError: () => notify('error'),
  })

  const canSubmit = isValidAmount(amount) && !create.isPending
  const visibleAccounts = accounts.data ?? []

  return (
    <div className="page">
      <div className="segmented">
        {(['expense', 'income'] as const).map((value) => (
          <button
            key={value}
            type="button"
            data-active={type === value}
            onClick={() => {
              haptic()
              setType(value)
              setCategoryId(null)
            }}
          >
            {value === 'expense' ? 'Расход' : 'Доход'}
          </button>
        ))}
      </div>

      <div className="card">
        <input
          className="amount-input"
          inputMode="decimal"
          placeholder="0"
          value={amount}
          onChange={(event) => setAmount(event.target.value)}
          aria-label="Сумма"
        />
        {amount !== '' && !isValidAmount(amount) && (
          <p className="error" style={{ textAlign: 'center' }}>
            Введите сумму числом, например 1250 или 1250,40
          </p>
        )}
      </div>

      <div className="card">
        <p className="section-title" style={{ margin: '0 0 10px' }}>
          Категория
        </p>
        <CategoryPicker
          categories={categories.data ?? []}
          value={categoryId}
          onChange={setCategoryId}
          order={kind === 'expense' ? recent.data : undefined}
        />
      </div>

      <input
        className="field"
        placeholder="Комментарий"
        value={note}
        onChange={(event) => setNote(event.target.value)}
      />

      {visibleAccounts.length > 1 && (
        <select
          className="field"
          value={accountId ?? ''}
          onChange={(event) => setAccountId(event.target.value || null)}
        >
          <option value="">Общий счёт (по умолчанию)</option>
          {visibleAccounts.map((account) => (
            <option key={account.id} value={account.id}>
              {account.is_shared ? '👥' : '👤'} {account.name}
            </option>
          ))}
        </select>
      )}

      {create.isError && <p className="error">{(create.error as Error).message}</p>}

      <button className="btn" type="button" disabled={!canSubmit} onClick={() => create.mutate()}>
        {create.isPending ? 'Сохраняем…' : 'Добавить'}
      </button>
    </div>
  )
}
