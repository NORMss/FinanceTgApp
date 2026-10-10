import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { api } from '../api'
import CategoryPicker from '../components/CategoryPicker'
import DayPicker from '../components/DayPicker'
import Disclosure from '../components/Disclosure'
import { dayKey, isoForDay, shiftDay, shortDay } from '../day'
import { formatMoney, isValidAmount, normalizeAmountInput } from '../format'
import { haptic, notify, webApp } from '../telegram'
import type { TransactionType } from '../types'

interface Props {
  currentUserId: string
  onDone: (message: string) => void
}

/**
 * Главный экран: добавить трату за три касания.
 *
 * Всё, что спрашивается всегда, стоит в один столбец и помещается на экран без
 * прокрутки: сумма, день, категория, кнопка. Комментарий и метки заполняются в одной
 * записи из десяти и убраны под раскрывающуюся строку — на телефоне два постоянно
 * висящих поля уводили кнопку «Добавить» за нижний край.
 *
 * Категории отсортированы так, что последние использованные стоят первыми — на практике
 * именно они закрывают почти весь ежедневный ввод, поэтому трёх рядов хватает.
 */
export default function AddPage({ currentUserId, onDone }: Props) {
  const queryClient = useQueryClient()
  const [type, setType] = useState<TransactionType>('expense')
  const [amount, setAmount] = useState('')
  const [day, setDay] = useState(dayKey())
  const [categoryId, setCategoryId] = useState<string | null>(null)
  const [note, setNote] = useState('')
  const [tags, setTags] = useState('')
  const [accountId, setAccountId] = useState<string | null>(null)
  // Растёт после каждой записи и пересобирает выбор категорий: список приезжает
  // в новом порядке, и раскрытые ряды должны схлопнуться обратно
  const [entry, setEntry] = useState(0)

  const kind = type === 'income' ? 'income' : 'expense'
  const categories = useQuery({ queryKey: ['categories', kind], queryFn: () => api.categories(kind) })
  const recent = useQuery({
    queryKey: ['recent-categories', kind],
    queryFn: () => api.recentCategories(kind),
  })
  const accounts = useQuery({ queryKey: ['accounts'], queryFn: api.accounts })
  const users = useQuery({ queryKey: ['users'], queryFn: api.users })

  // Выбранный день живёт между записями, но не между сутками. Telegram сворачивает
  // Mini App, не выгружая его, и день, переживший ночь в свёрнутом окне, молча уводил бы
  // утренние траты назад: «Сегодня» превратилось бы во «Вчера», «Вчера» — в позавчера
  useEffect(() => {
    let seen = dayKey()
    const refresh = () => {
      const now = dayKey()
      if (document.visibilityState !== 'visible' || now === seen) return
      seen = now
      setDay(now)
    }
    document.addEventListener('visibilitychange', refresh)
    // Сворачивание внутри самого Telegram страницу не прячет — о возврате сообщает он
    webApp?.onEvent('activated', refresh)
    return () => {
      document.removeEventListener('visibilitychange', refresh)
      webApp?.offEvent('activated', refresh)
    }
  }, [])

  const today = dayKey()
  // «за вчера», «за 5 окт» — пусто для сегодняшнего дня. День остаётся после записи,
  // и забытая «Вчера» — единственная ошибка формы, которую человек не замечает: сумма
  // и категория видны в истории сразу, а день расходится с реальностью молча. Поэтому
  // он написан там, куда смотрят перед касанием, — на кнопке, — и повторён в подтверждении
  const backdated =
    day === today ? '' : ` за ${day === shiftDay(today, -1) ? 'вчера' : shortDay(day)}`

  const create = useMutation({
    mutationFn: () =>
      api.createTransaction({
        type,
        amount: normalizeAmountInput(amount),
        category_id: categoryId,
        account_id: accountId,
        note: note.trim(),
        tags,
        // Сегодняшний день не шлём: время проставит сервер, и в истории окажется
        // настоящий момент записи, а не полдень
        occurred_at: day === today ? undefined : isoForDay(day),
      }),
    onSuccess: (tx) => {
      notify('success')
      onDone(
        `${type === 'income' ? 'Доход' : 'Расход'} ${formatMoney(tx.amount_minor)} записан${backdated}`,
      )
      setAmount('')
      setNote('')
      // Категорию снимаем: у следующей траты она почти всегда другая, а оставшийся
      // выбранным чипс выглядит так, будто его уже нажали, — и «Кафе» уезжает в «Продукты»
      setCategoryId(null)
      setEntry((current) => current + 1)
      // День не трогаем: чеки за прошлые числа вносят пачкой, и выбирать дату заново
      // перед каждым — работа, ради которой их перестают вносить вовсе. Чтобы оставленный
      // день не забылся, его называет сама кнопка записи (см. backdated)

      // Метку не сбрасываем намеренно: траты в отпуске идут подряд, и проставлять
      // «отпуск» заново для каждой — работа, ради которой метками перестают пользоваться

      // Сумма меняет всё: список, сводку, остатки и взаиморасчёты
      queryClient.invalidateQueries()
    },
    onError: () => notify('error'),
  })

  const canSubmit = isValidAmount(amount) && !create.isPending
  // Свёрнутая строка обязана показывать, что в ней лежит: метка живёт между записями,
  // и «отпуск», забытый в поле, разъехался бы по всем тратам после возвращения
  const details = [note.trim(), tags.trim() && `🏷 ${tags.trim()}`].filter(Boolean).join(' · ')
  const visibleAccounts = accounts.data ?? []
  // Свой счёт — умолчание. Общий выбирают руками: трата с него делится пополам
  // и превращается в долг второго участника, а это должно быть решением, а не побочным
  // эффектом того, что общий счёт оказался первым в списке
  const myAccount = visibleAccounts.find(
    (account) => !account.is_shared && account.owner_id === currentUserId,
  )
  const selected = visibleAccounts.find((account) => account.id === accountId)
  // Выбран чужой личный счёт — значит, запись делается за другого человека. Стоит сказать
  // об этом прямо: в историю и отчёт трата попадёт к нему, а не к тому, кто её вносит
  const forSomeoneElse =
    selected && !selected.is_shared && selected.owner_id && selected.owner_id !== currentUserId
      ? users.data?.find((user) => user.id === selected.owner_id)
      : undefined

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
        <DayPicker value={day} onChange={setDay} />
      </div>

      <div className="card">
        <p className="section-title" style={{ margin: '0 0 10px' }}>
          Категория
        </p>
        <CategoryPicker
          key={`${kind}:${entry}`}
          categories={categories.data ?? []}
          value={categoryId}
          onChange={setCategoryId}
          order={recent.data}
          collapsible
        />
      </div>

      <Disclosure title="Комментарий и метки" summary={details}>
        <input
          className="field"
          placeholder="Комментарий"
          value={note}
          onChange={(event) => setNote(event.target.value)}
        />
        {/* Метка отвечает на «в рамках чего»: отпуск размазан по такси, кафе и жилью,
            и вычесть его из отчёта исключением категорий невозможно */}
        <input
          className="field"
          placeholder="Метки через запятую — отпуск, ремонт"
          value={tags}
          onChange={(event) => setTags(event.target.value)}
          aria-label="Метки"
        />
      </Disclosure>

      {visibleAccounts.length > 1 && (
        <>
          <select
            className="field"
            value={accountId ?? ''}
            onChange={(event) => setAccountId(event.target.value || null)}
            aria-label="Счёт"
          >
            <option value="">
              👤 {myAccount ? `${myAccount.name} (по умолчанию)` : 'Свой счёт (по умолчанию)'}
            </option>
            {visibleAccounts
              .filter((account) => account.id !== myAccount?.id)
              .map((account) => (
                <option key={account.id} value={account.id}>
                  {account.is_shared ? '👥' : '👤'} {account.name}
                </option>
              ))}
          </select>
          {selected?.is_shared && (
            <p className="hint" style={{ marginTop: 0 }}>
              Трата с общего счёта делится поровну — второй участник окажется должен вам
              половину.
            </p>
          )}
          {forSomeoneElse && (
            <p className="hint" style={{ marginTop: 0 }}>
              Трата будет числиться за {forSomeoneElse.display_name}, а не за вами —
              и в истории, и в отчёте.
            </p>
          )}
        </>
      )}

      {create.isError && <p className="error">{(create.error as Error).message}</p>}

      <button className="btn" type="button" disabled={!canSubmit} onClick={() => create.mutate()}>
        {create.isPending ? 'Сохраняем…' : `Добавить${backdated}`}
      </button>
    </div>
  )
}
