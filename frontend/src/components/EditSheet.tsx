import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../api'
import { formatMoney, isValidAmount, normalizeAmountInput, toAmountInput, toMinor } from '../format'
import { haptic, notify } from '../telegram'
import type { Account, Category, Transaction, TransactionType } from '../types'
import CategoryPicker from './CategoryPicker'
import ErrorNote from './ErrorNote'

interface Props {
  tx: Transaction
  categories: Category[]
  accounts: Account[]
  onClose: () => void
  onDone: (message: string) => void
}

/** `2026-08-15T10:30:00Z` -> `2026-08-15T10:30` для <input type="datetime-local">. */
function toLocalInput(iso: string): string {
  const date = new Date(iso)
  const shifted = new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
  return shifted.toISOString().slice(0, 16)
}

/**
 * Правка записи, уже попавшей в историю.
 *
 * Открывается поверх списка, а не отдельным экраном: пользователь пришёл сюда из
 * конкретной строки и должен видеть, что правит. Отправляем только изменённые поля —
 * так случайный тап по «Сохранить» не перезаписывает то, чего не трогали.
 */
export default function EditSheet({ tx, categories, accounts, onClose, onDone }: Props) {
  const queryClient = useQueryClient()
  const [type, setType] = useState<TransactionType>(tx.type)
  const [amount, setAmount] = useState(toAmountInput(tx.amount_minor))
  const [categoryId, setCategoryId] = useState<string | null>(tx.category_id)
  const [note, setNote] = useState(tx.note)
  const [accountId, setAccountId] = useState(tx.account_id)
  const [occurredAt, setOccurredAt] = useState(toLocalInput(tx.occurred_at))

  const users = useQuery({ queryKey: ['users'], queryFn: api.users })
  const author = users.data?.find((user) => user.id === tx.author_id)

  const save = useMutation({
    mutationFn: () => {
      const payload: Parameters<typeof api.updateTransaction>[1] = {}
      if (type !== tx.type) payload.type = type
      // Сумму шлём, только если её действительно поменяли: пересчёт долей на сервере
      // затирает ручное деление, и делать это «на всякий случай» нельзя
      if (toMinor(amount) !== tx.amount_minor) payload.amount = normalizeAmountInput(amount)
      if (categoryId !== tx.category_id) payload.category_id = categoryId
      if (note.trim() !== tx.note) payload.note = note.trim()
      if (accountId !== tx.account_id) payload.account_id = accountId
      if (occurredAt !== toLocalInput(tx.occurred_at)) {
        payload.occurred_at = new Date(occurredAt).toISOString()
      }
      return api.updateTransaction(tx.id, payload)
    },
    onSuccess: (updated) => {
      notify('success')
      onDone(`Изменено: ${formatMoney(updated.amount_minor)}`)
      queryClient.invalidateQueries()
      onClose()
    },
    onError: () => notify('error'),
  })

  const remove = useMutation({
    mutationFn: () => api.deleteTransaction(tx.id),
    onSuccess: () => {
      notify('success')
      onDone('Операция удалена')
      queryClient.invalidateQueries()
      onClose()
    },
  })

  const kind = type === 'income' ? 'income' : 'expense'
  const visible = categories.filter((item) => item.kind === kind)
  const canSave = isValidAmount(amount) && !save.isPending

  return (
    <div className="sheet-backdrop" onClick={onClose} role="presentation">
      <div className="sheet" onClick={(event) => event.stopPropagation()} role="dialog">
        <div className="sheet__grip" />

        {type !== 'transfer' && (
          <div className="segmented">
            {(['expense', 'income'] as const).map((value) => (
              <button
                key={value}
                type="button"
                data-active={type === value}
                onClick={() => {
                  haptic()
                  setType(value)
                  setCategoryId(null) // категории расходов и доходов не пересекаются
                }}
              >
                {value === 'expense' ? 'Расход' : 'Доход'}
              </button>
            ))}
          </div>
        )}

        <input
          className="amount-input"
          inputMode="decimal"
          value={amount}
          onChange={(event) => setAmount(event.target.value)}
          aria-label="Сумма"
        />
        {!isValidAmount(amount) && (
          <p className="error" style={{ textAlign: 'center' }}>
            Сумма числом, например 1250 или 1250,40
          </p>
        )}

        {type !== 'transfer' && (
          <>
            <p className="section-title">Категория</p>
            <CategoryPicker categories={visible} value={categoryId} onChange={setCategoryId} />
          </>
        )}

        <input
          className="field"
          placeholder="Комментарий"
          value={note}
          onChange={(event) => setNote(event.target.value)}
        />

        <input
          className="field"
          type="datetime-local"
          value={occurredAt}
          onChange={(event) => setOccurredAt(event.target.value)}
          aria-label="Дата и время"
        />

        {accounts.length > 1 && (
          <select
            className="field"
            value={accountId}
            onChange={(event) => setAccountId(event.target.value)}
            aria-label="Счёт"
          >
            {accounts.map((account) => (
              <option key={account.id} value={account.id}>
                {account.is_shared ? '👥' : '👤'} {account.name}
              </option>
            ))}
          </select>
        )}

        <ErrorNote error={save.error ?? remove.error} />

        <div className="sheet__actions">
          <button className="btn btn--ghost" type="button" onClick={onClose}>
            Отмена
          </button>
          <button className="btn" type="button" disabled={!canSave} onClick={() => save.mutate()}>
            {save.isPending ? 'Сохраняем…' : 'Сохранить'}
          </button>
        </div>

        <div className="sheet__footer">
          <span className="hint">
            {author ? `Записал: ${author.display_name}` : ''}
            {tx.source === 'sheet' ? ' · из таблицы' : ''}
            {tx.source === 'bot' ? ' · из чата' : ''}
          </span>
          <button
            className="btn btn--danger"
            type="button"
            disabled={remove.isPending}
            onClick={() => remove.mutate()}
          >
            Удалить
          </button>
        </div>
      </div>
    </div>
  )
}
