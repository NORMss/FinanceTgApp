/**
 * Проверки интерфейса на живом демо.
 *
 * Не юнит-тесты компонентов: экран отчёта — это в первую очередь связка «фильтр
 * поехал -> запрос ушёл -> цифры сошлись», и проверять её осмысленно только целиком,
 * с настоящим сервером и настоящими данными. Компонентные тесты потребовали бы
 * jsdom, testing-library и моков API — три зависимости ради проверок, которые
 * ничего не знают о том, сходится ли итог с историей.
 *
 * Живут в scripts/ рядом со съёмкой скриншотов и переиспользуют её браузер:
 * во фронт браузерный драйвер не тащим.
 *
 *   make demo                      # в одном терминале
 *   cd scripts && npm install && npm run test:ui
 *
 * CHROME_PATH и DEMO_URL — как у скриншотов.
 */

import path from 'node:path'
import process from 'node:process'
import puppeteer from 'puppeteer-core'

const BASE = process.env.DEMO_URL ?? 'http://127.0.0.1:8000'
const CHROME =
  process.env.CHROME_PATH ?? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const VIEWPORT = { width: 390, height: 844, deviceScaleFactor: 1 }

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

// --- крошечный раннер -------------------------------------------------------

const tests = []
const test = (name, fn) => tests.push({ name, fn })

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

function assertEqual(actual, expected, message) {
  if (actual !== expected) {
    throw new Error(`${message}\n  ожидалось: ${expected}\n  получено:  ${actual}`)
  }
}

// --- помощники по странице --------------------------------------------------

/** Ждёт, пока экран догрузит данные: иначе проверяем надпись «Загружаем…». */
async function settled(page) {
  await page.waitForFunction(() => !document.body.innerText.includes('Загружаем'), {
    timeout: 15_000,
  })
  await wait(200)
}

async function openTab(page, label) {
  await clickByText(page, '.tabbar button', label)
  await settled(page)
}

async function clickByText(page, selector, text) {
  const handle = await page.evaluateHandle(
    (sel, needle) =>
      [...document.querySelectorAll(sel)].find((node) =>
        node.textContent.trim().includes(needle),
      ) ?? null,
    selector,
    text,
  )
  const element = handle.asElement()
  if (!element) throw new Error(`не нашёл «${text}» по селектору ${selector}`)
  await element.click()
  await wait(400)
}

/** Три цифры из карточки итогов, как их видит человек. */
async function totals(page) {
  return page.$eval('.totals', (node) => {
    const cells = [...node.querySelectorAll('div')]
    const value = (label) =>
      cells.find((cell) => cell.querySelector('span')?.textContent === label)?.querySelector('b')
        ?.textContent ?? ''
    return {
      expense: value('Расходы'),
      income: value('Доходы'),
      saldo: value('Сальдо'),
    }
  })
}

/** Копейки из строки «1 234,56» — чтобы сравнивать суммы, а не их вёрстку. */
function toMinor(text) {
  const cleaned = text.replace(/[\s  ]/g, '').replace('−', '-').replace('+', '')
  const [whole, cents = '0'] = cleaned.split(',')
  return Number(whole) * 100 + Number(cents.padEnd(2, '0'))
}

async function periodLabel(page) {
  return page.$eval('.totals__meta span', (node) => node.textContent.trim())
}

async function categoryNames(page) {
  return page.$$eval('.card--tight .row__title', (nodes) =>
    nodes.map((node) => node.textContent.trim()),
  )
}

async function newPage(browser) {
  const page = await browser.newPage()
  await page.setViewport(VIEWPORT)
  await page.goto(BASE, { waitUntil: 'networkidle0' })
  await page.waitForSelector('.tabbar', { timeout: 15_000 })
  // Настройки отчёта переживают перезагрузку — между тестами их надо стирать,
  // иначе исключения из одного теста поедут в следующий
  await page.evaluate(() => window.localStorage.clear())
  await page.reload({ waitUntil: 'networkidle0' })
  await page.waitForSelector('.tabbar', { timeout: 15_000 })
  return page
}

// --- сами проверки ----------------------------------------------------------

test('отчёт показывает итоги и подпись периода', async (page) => {
  await openTab(page, 'Отчёт')

  const { expense, income, saldo } = await totals(page)
  assert(toMinor(expense) > 0, 'расходы за месяц нулевые — демо не наполнено?')
  assert(toMinor(income) > 0, 'доходы за месяц нулевые')
  assert(saldo.length > 0, 'сальдо не выведено')

  // R3: подпись периода приходит с сервера и описывает именно показанные деньги
  const label = await periodLabel(page)
  assert(/^[А-Я][а-я]+( \d{4})?$/.test(label), `подпись периода выглядит странно: «${label}»`)

  const perDay = await page.$$eval('.totals__meta span', (nodes) =>
    nodes.map((node) => node.textContent),
  )
  assert(perDay.some((text) => text.includes('в день')), 'нет темпа трат в день')
})

test('листание месяцев меняет период', async (page) => {
  await openTab(page, 'Отчёт')

  await clickByText(page, '.segmented button', '⋯')
  await clickByText(page, '.chip', 'Листать месяцы')
  await settled(page)

  const current = await periodLabel(page)
  await page.click('[aria-label="Предыдущий месяц"]')
  await settled(page)
  const previous = await periodLabel(page)

  assert(current !== previous, `подпись не изменилась при листании: обе «${current}»`)

  // R2: вперёд дальше текущего месяца не пускаем — данных там заведомо нет
  await page.click('[aria-label="Следующий месяц"]')
  await settled(page)
  assertEqual(await periodLabel(page), current, 'листание вперёд не вернуло текущий месяц')

  const disabled = await page.$eval('[aria-label="Следующий месяц"]', (node) => node.disabled)
  assert(disabled, 'кнопка «вперёд» активна на текущем месяце')
})

test('свой диапазон применяется', async (page) => {
  await openTab(page, 'Отчёт')

  const today = new Date()
  const first = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-01`
  const fifth = first.replace(/01$/, '05')

  await clickByText(page, '.segmented button', '⋯')
  await page.$eval('[aria-label="Начало периода"]', (node, value) => {
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype, 'value',
    ).set
    setter.call(node, value)
    node.dispatchEvent(new Event('input', { bubbles: true }))
  }, first)
  await page.$eval('[aria-label="Конец периода"]', (node, value) => {
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype, 'value',
    ).set
    setter.call(node, value)
    node.dispatchEvent(new Event('input', { bubbles: true }))
  }, fifth)
  await clickByText(page, '.sheet .btn', 'Показать')
  await settled(page)

  assertEqual(await periodLabel(page), '1–5 ' + monthGenitive(today), 'подпись диапазона не та')
})

function monthGenitive(date) {
  return [
    'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
    'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря',
  ][date.getMonth()]
}

test('исключение категории уменьшает итог и объясняет, на сколько', async (page) => {
  await openTab(page, 'Отчёт')

  const before = toMinor((await totals(page)).expense)
  const names = await categoryNames(page)
  const victim = names.find((name) => name === 'Продукты') ?? names[0]

  await clickByText(page, '.chip', 'Что не показывать')
  await page.waitForSelector('.sheet')
  await page.click(`[aria-label="Скрыть ${victim}"]`)
  await clickByText(page, '.sheet .btn', 'Скрыть')
  await settled(page)

  const after = toMinor((await totals(page)).expense)
  assert(after < before, `итог не уменьшился: было ${before}, стало ${after}`)

  // R1: скрытое видно рядом с итогом, и суммы сходятся
  const excluded = await page.$eval('.totals__excluded', (node) => node.textContent)
  const hidden = toMinor(excluded.match(/Скрыто ([\d\s  ,]+)/)[1])
  assertEqual(after + hidden, before, 'показанное плюс скрытое не равно полной сумме')

  // Скрытая категория ушла из списка
  assert(!(await categoryNames(page)).includes(victim), `«${victim}» осталась в списке`)

  // И возвращается сбросом
  await clickByText(page, '.chip', 'Сбросить')
  await settled(page)
  assertEqual(toMinor((await totals(page)).expense), before, 'сброс не вернул полный итог')
})

test('исключения переживают перезагрузку', async (page) => {
  await openTab(page, 'Отчёт')

  await clickByText(page, '.chip', 'Что не показывать')
  await page.waitForSelector('.sheet')
  await page.click('[aria-label="Скрыть Продукты"]')
  await clickByText(page, '.sheet .btn', 'Скрыть')
  await settled(page)
  const after = toMinor((await totals(page)).expense)

  // R5: mini app открывают на двадцать секунд, и собирать вид заново каждый раз
  // — верный способ перестать им пользоваться
  await page.reload({ waitUntil: 'networkidle0' })
  await page.waitForSelector('.tabbar')
  await openTab(page, 'Отчёт')

  assertEqual(toMinor((await totals(page)).expense), after, 'исключение забылось после перезапуска')
  // Рядов чипсов на экране несколько (люди, счета, исключения) — ищем по всем
  const chips = await page.$$eval('.chips', (nodes) => nodes.map((node) => node.textContent))
  assert(
    chips.some((text) => text.includes('Скрыто')),
    'чипс не показывает, что фильтр активен',
  )
})

test('тап по категории уводит в историю с этим фильтром', async (page) => {
  await openTab(page, 'Отчёт')

  const names = await categoryNames(page)
  const target = names[0]
  await clickByText(page, '.card--tight .row', target)
  await settled(page)

  // R4: провал открывает Историю, и в ней уже стоит та самая категория
  const active = await page.$eval('.tabbar button[data-active="true"]', (n) => n.textContent)
  assert(active.includes('История'), `открылась не История, а «${active}»`)

  const chips = await page.$eval('.page', (node) => node.textContent)
  assert(chips.includes(target), `фильтр по «${target}» не подставлен`)

  const rows = await page.$$('.row--tappable')
  assert(rows.length > 0, 'история пуста — фильтр отсёк всё')
})

test('переключатель расходов и доходов меняет список', async (page) => {
  await openTab(page, 'Отчёт')

  const expenses = await categoryNames(page)
  await clickByText(page, '.segmented button', 'Доходы')
  await settled(page)
  const incomes = await categoryNames(page)

  // R10: доходные категории заводятся, но отчёта по ним раньше не было вовсе
  assert(incomes.length > 0, 'разбивка доходов пуста')
  assert(
    incomes.some((name) => !expenses.includes(name)),
    'список доходов совпал со списком расходов',
  )
})

test('«по долям» отличается от «по счёту»', async (page) => {
  await openTab(page, 'Отчёт')

  const byAccount = await page.$$eval('.btn--slim', (nodes) =>
    nodes.map((node) => node.textContent.trim()),
  )
  await clickByText(page, '.section-title--row .btn--link', 'по долям')
  await settled(page)
  const byShares = await page.$$eval('.btn--slim', (nodes) =>
    nodes.map((node) => node.textContent.trim()),
  )

  // R11: у общего счёта нет владельца, поэтому по счёту трата целиком числится
  // за тем, кто её записал, а по долям делится пополам — цифры обязаны разойтись,
  // иначе переключатель ничего не переключает
  assert(byAccount.length === 2 && byShares.length === 2, 'ожидались два участника')
  assert(
    byAccount.join() !== byShares.join(),
    `цифры не изменились: ${byAccount.join(' / ')}`,
  )
})

test('график динамики раскрывается и рисует столбики', async (page) => {
  await openTab(page, 'Отчёт')

  await clickByText(page, '.section-title--row .btn--link', 'показать')
  await page.waitForSelector('.chart', { timeout: 15_000 })

  // R15: демо наполняет три месяца, значит столбиков должно быть три
  const bars = await page.$$eval('.chart__col', (nodes) => nodes.length)
  assert(bars >= 2, `столбиков всего ${bars} — сравнивать нечего`)

  const heights = await page.$$eval('.chart__col > i', (nodes) =>
    nodes.map((node) => node.style.height),
  )
  assert(heights.every((height) => height.endsWith('%')), 'высота столбика не задана')
})

test('лимит категории показан полосой и подписью', async (page) => {
  await openTab(page, 'Отчёт')

  // R16: демо ставит лимиты на Продукты, Кафе и Транспорт
  const limited = await page.$$eval('.card--tight .row', (nodes) =>
    nodes
      .filter((node) => node.querySelector('.row__body .row__sub'))
      .map((node) => ({
        name: node.querySelector('.row__title').textContent.trim(),
        note: node.querySelector('.row__body .row__sub').textContent.trim(),
      })),
  )
  assert(limited.length > 0, 'ни одной категории с лимитом — демо не наполнено?')
  assert(
    limited.some((item) => item.note.startsWith('из ') || item.note.startsWith('перебор ')),
    `подпись лимита не найдена: ${JSON.stringify(limited)}`,
  )
})

test('крупнейшие траты и повторяющиеся платежи выведены', async (page) => {
  await openTab(page, 'Отчёт')

  // Именно textContent: innerText отдаёт только отрисованное, и у длинной
  // страницы нижние секции в него не попадают
  const text = await page.$eval('.page', (node) => node.textContent)
  // R9 и R17
  assert(text.includes('Самые крупные'), 'нет блока крупнейших трат')
  assert(text.includes('Повторяется'), 'нет блока повторяющихся платежей')

  const largest = await page.evaluate(() => {
    const title = [...document.querySelectorAll('.section-title')].find(
      (node) => node.textContent.trim() === 'Самые крупные',
    )
    return [...title.nextElementSibling.querySelectorAll('.row__amount')].map(
      (node) => node.textContent.trim(),
    )
  })
  assertEqual(largest.length, 5, 'ожидалось пять крупнейших трат')

  const amounts = largest.map(toMinor)
  const sorted = [...amounts].sort((a, b) => b - a)
  assertEqual(amounts.join(), sorted.join(), 'крупнейшие траты не отсортированы по убыванию')
})

test('фильтр по метке вычитает отпуск', async (page) => {
  await openTab(page, 'Отчёт')

  // Отпуск в демо стоит в прошлом месяце
  await clickByText(page, '.segmented button', 'Прошлый')
  await settled(page)
  const before = toMinor((await totals(page)).expense)

  await clickByText(page, '.chip', 'Что не показывать')
  await page.waitForSelector('.sheet')
  await clickByText(page, '.sheet .chip--ghost', 'отпуск')
  // Сумму по метке клиент не знает — кнопка говорит «Скрыть» без цифры
  await clickByText(page, '.sheet .btn', 'Скрыть')
  await settled(page)

  // R18: метка режет поперёк категорий — исключением категорий этого не сделать
  const after = toMinor((await totals(page)).expense)
  assert(after < before, `метка ничего не вычла: было ${before}, стало ${after}`)
})

test('сохранённый вид возвращает набор фильтров', async (page) => {
  await openTab(page, 'Отчёт')

  await clickByText(page, '.chip', 'Что не показывать')
  await page.waitForSelector('.sheet')
  await page.click('[aria-label="Скрыть Продукты"]')
  await clickByText(page, '.sheet .btn', 'Скрыть')
  await settled(page)
  const filtered = toMinor((await totals(page)).expense)

  // window.prompt в headless не открывается — подменяем на время нажатия
  await page.evaluate(() => {
    window.prompt = () => 'Тестовый вид'
  })
  await clickByText(page, '.icon-row .btn', 'Вид')
  await page.waitForFunction(
    () => document.body.innerText.includes('сохранён'),
    { timeout: 10_000 },
  )

  await clickByText(page, '.chip', 'Сбросить')
  await settled(page)
  assert(toMinor((await totals(page)).expense) > filtered, 'сброс не вернул полный итог')

  // R19: вид восстанавливает те же фильтры одним касанием
  await clickByText(page, '.chip--ghost', 'Тестовый вид')
  await settled(page)
  assertEqual(toMinor((await totals(page)).expense), filtered, 'вид не восстановил фильтры')
})

// --- форма ввода ------------------------------------------------------------

/** Сколько рядов занимают чипсы категорий: чипсы одного ряда стоят на одной высоте. */
async function categoryRows(page) {
  return page.$$eval(
    '.chips--roots .chip',
    (nodes) => new Set(nodes.map((node) => node.offsetTop)).size,
  )
}

async function categoryChips(page) {
  return page.$$eval('.chips--roots .chip', (nodes) =>
    nodes.map((node) => node.textContent.trim()),
  )
}

/** Сколько чипсов категорий подсвечено — и корней, и уточнений под ними. */
async function activeCategories(page) {
  return page.$$eval('.picker .chip[data-active="true"]', (nodes) => nodes.length)
}

/** Ставит день в календаре «Другая»: родной выбор даты драйверу не открыть. */
async function pickDate(page, key) {
  await page.$eval(
    '.segmented--soft input[type="date"]',
    (input, value) => {
      // Мимо сеттера React изменение не заметит: он сверяет значение со своим
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, value)
      input.dispatchEvent(new Event('input', { bubbles: true }))
      input.dispatchEvent(new Event('change', { bubbles: true }))
    },
    key,
  )
  await wait(300)
}

/** Подпись выбранного дня в переключателе «Другая / Вчера / Сегодня». */
async function pickedDay(page) {
  return page.$eval('.segmented--soft', (node) => {
    const active = [...node.children].find((child) => child.dataset.active === 'true')
    return active ? active.textContent.trim() : ''
  })
}

test('форма ввода помещается на экран без прокрутки', async (page) => {
  await openTab(page, 'Добавить')

  // U1: «трата за три касания» держится на том, что все три цели видны сразу.
  // Кнопка записи, уехавшая под панель вкладок, добавляет к ним прокрутку
  const button = await page.$eval('.page > .btn', (node) => node.getBoundingClientRect().bottom)
  const tabbar = await page.$eval('.tabbar', (node) => node.getBoundingClientRect().top)
  assert(button <= tabbar, `кнопка «Добавить» уходит под вкладки: ${button} > ${tabbar}`)
})

test('категории свёрнуты до трёх рядов и раскрываются последним чипсом', async (page) => {
  await openTab(page, 'Добавить')

  // U2: на телефоне развёрнутый справочник занимал полэкрана
  assertEqual(await categoryRows(page), 3, 'свёрнутый список занимает не три ряда')

  const chips = await categoryChips(page)
  assert(
    chips[chips.length - 1].startsWith('Ещё'),
    `последний чипс — «${chips[chips.length - 1]}», а не «Ещё N»`,
  )

  await clickByText(page, '.chips--roots .chip', 'Ещё')
  assert(await categoryRows(page) > 3, 'после раскрытия список остался в трёх рядах')
  assert(
    (await categoryChips(page)).length > chips.length,
    'раскрытие не добавило ни одной категории',
  )

  await clickByText(page, '.chips--roots .chip', 'Свернуть')
  assertEqual(await categoryRows(page), 3, 'свернуть обратно не получилось')
})

test('запись за вчера ложится во вчерашний день и поднимает категорию', async (page) => {
  await openTab(page, 'Добавить')

  // Второй чипс: заведомо виден и заведомо не первый — значит, его переезд наверх
  // после записи ни с чем не спутать
  const target = (await categoryChips(page))[1]

  await page.type('.amount-input', '345')
  await clickByText(page, '.chips--roots .chip', target)
  await clickByText(page, '.segmented--soft button', 'Вчера')
  await clickByText(page, '.page > .btn', 'Добавить')
  await page.waitForFunction(() => document.body.innerText.includes('записан'), {
    timeout: 15_000,
  })
  await settled(page)

  // U3: порядок категорий задаёт момент записи, а не дата операции. Иначе трата
  // задним числом выбирала бы категорию, которая никуда не переезжает
  assertEqual((await categoryChips(page))[0], target, 'категория не встала первой')

  // U4: день остаётся для следующей записи — чеки за прошлые числа вносят пачкой.
  // Забытая «Вчера» — единственная ошибка формы, которую человек не замечает,
  // поэтому оставленный день обязана называть сама кнопка
  assertEqual(await pickedDay(page), 'Вчера', 'день сбросился после записи')
  assertEqual(
    await page.$eval('.page > .btn', (node) => node.textContent.trim()),
    'Добавить за вчера',
    'кнопка не называет оставленный день',
  )

  // U6: категория, наоборот, снимается — у следующей траты она почти всегда другая
  assertEqual(await activeCategories(page), 0, 'категория осталась выбранной после записи')

  await openTab(page, 'История')
  // Первого числа вчерашний день лежит в прошлом месяце, а история открыта на этом
  if (new Date().getDate() === 1) {
    await clickByText(page, '.segmented button', 'Прошлый')
    await settled(page)
  }
  const yesterday = await page.evaluate(() => {
    const title = [...document.querySelectorAll('.section-title--row')].find((node) =>
      node.textContent.startsWith('Вчера'),
    )
    return title?.nextElementSibling.textContent ?? ''
  })
  assert(yesterday.includes('345'), 'трата не попала во вчерашний день истории')
})

test('своя дата остаётся на следующие записи', async (page) => {
  await openTab(page, 'Добавить')

  // Три дня назад: заведомо не «Вчера», так что подпись на переключателе — число
  const past = new Date()
  past.setDate(past.getDate() - 3)
  const key = [past.getFullYear(), past.getMonth() + 1, past.getDate()]
    .map((part) => String(part).padStart(2, '0'))
    .join('-')

  await pickDate(page, key)
  const label = await pickedDay(page)
  assert(label.startsWith(`${past.getDate()} `), `переключатель показывает «${label}»`)

  // U4: две записи подряд, дату выбирали один раз. Копейки — чтобы суммы не совпали
  // с демо-данными того же дня
  const amounts = ['347,11', '349,13']
  for (const amount of amounts) {
    await page.type('.amount-input', amount)
    await clickByText(page, '.page > .btn', 'Добавить')
    // Не по подтверждению: от первой записи оно ещё висит, когда уходит вторая
    await page.waitForFunction(() => document.querySelector('.amount-input').value === '', {
      timeout: 15_000,
    })
    await settled(page)
    assertEqual(await pickedDay(page), label, 'дата сбросилась после записи')
  }

  await openTab(page, 'История')
  if (past.getMonth() !== new Date().getMonth()) {
    await clickByText(page, '.segmented button', 'Прошлый')
    await settled(page)
  }
  const day = await page.evaluate((title) => {
    const node = [...document.querySelectorAll('.section-title--row')].find((item) =>
      item.textContent.startsWith(title),
    )
    return node?.nextElementSibling.textContent ?? ''
  }, `${past.getDate()} ${monthGenitive(past)}`)
  for (const amount of amounts) {
    assert(day.includes(amount), `трата ${amount} не попала в выбранный день истории`)
  }
})

test('фильтр по счёту на отчёте свёрнут в строку', async (page) => {
  await openTab(page, 'Отчёт')

  // U5: ряд из четырёх чипсов стоял выше первой цифры отчёта и отодвигал её за экран
  const head = await page.$eval('.disclosure__head', (node) => node.textContent)
  assert(head.includes('Кошелёк'), `строка счёта выглядит иначе: «${head}»`)
  assert(head.includes('Все счета'), 'свёрнутая строка не показывает текущий выбор')
  assertEqual(
    await page.$$eval('.disclosure__body', (nodes) => nodes.length),
    0,
    'строка счёта раскрыта сразу',
  )

  await page.click('.disclosure__head')
  await wait(300)
  const chips = await page.$$eval('.disclosure__body .chip', (nodes) =>
    nodes.map((node) => node.textContent.trim()),
  )
  assert(
    chips.some((text) => text.includes('Общий счёт')),
    `в раскрытом фильтре нет счетов: ${chips.join(' / ')}`,
  )
})

// --- запуск -----------------------------------------------------------------

const browser = await puppeteer.launch({
  executablePath: CHROME,
  args: ['--hide-scrollbars', '--force-color-profile=srgb'],
})

let failed = 0
try {
  for (const { name, fn } of tests) {
    const page = await newPage(browser)
    try {
      await fn(page)
      console.log(`  ✓ ${name}`)
    } catch (error) {
      failed += 1
      console.error(`  ✗ ${name}`)
      console.error(`    ${error.message.split('\n').join('\n    ')}`)
      const shot = path.join(process.cwd(), `ui-failure-${failed}.png`)
      await page.screenshot({ path: shot })
      console.error(`    снимок: ${shot}`)
    } finally {
      await page.close()
    }
  }
} finally {
  await browser.close()
}

console.log(
  failed === 0
    ? `\nВсе проверки прошли: ${tests.length}`
    : `\nПровалено ${failed} из ${tests.length}`,
)
process.exit(failed === 0 ? 0 : 1)
