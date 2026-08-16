/**
 * Снимает скриншоты Mini App для README.
 *
 * Требует запущенного демо и установленного Chrome. Зависимости живут в scripts/,
 * отдельно от приложения: снимки обновляют раз в несколько месяцев, и тащить
 * браузерный драйвер в зависимости фронта ради этого незачем.
 *
 *   make demo                  # в одном терминале
 *   cd scripts && npm install && npm run screenshots
 *
 * Путь к Chrome можно задать через CHROME_PATH, адрес демо — через DEMO_URL.
 *
 * Размер кадра — 390×844, это iPhone 14/15. Приложение живёт внутри Telegram,
 * и показывать его в широком окне десктопа бессмысленно: вёрстка рассчитана
 * на телефон.
 */

import { mkdir } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import puppeteer from 'puppeteer-core'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const BASE = process.env.DEMO_URL ?? 'http://127.0.0.1:8000'
const OUT = path.join(HERE, '..', 'docs', 'screenshots')
const CHROME =
  process.env.CHROME_PATH ??
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'

const VIEWPORT = { width: 390, height: 844, deviceScaleFactor: 2 }

/** Палитра Telegram: приложение читает эти переменные и без самого Telegram. */
const THEMES = {
  light: {
    'bg-color': '#ffffff',
    'secondary-bg-color': '#f2f2f7',
    'text-color': '#000000',
    'hint-color': '#8a8a8e',
    'link-color': '#2a7fd4',
    'button-color': '#2a7fd4',
    'button-text-color': '#ffffff',
  },
  dark: {
    'bg-color': '#1c1c1e',
    'secondary-bg-color': '#000000',
    'text-color': '#ffffff',
    'hint-color': '#8d8d93',
    'link-color': '#6ab3f3',
    'button-color': '#2a7fd4',
    'button-text-color': '#ffffff',
  },
}

const SHOTS = [
  { name: 'add', tab: 'Добавить', prepare: pickCategory },
  { name: 'history', tab: 'История' },
  { name: 'stats', tab: 'Отчёт' },
  { name: 'edit', tab: 'История', prepare: openEditSheet },
  { name: 'categories', tab: 'Ещё', prepare: openCategories },
  { name: 'category-delete', tab: 'Ещё', prepare: openDeletePanel },
  { name: 'more', tab: 'Ещё' },
]

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

/**
 * Ждёт, пока экран догрузит данные.
 *
 * Без этого получаются кадры с надписью «Загружаем…»: запрос к API уходит уже после
 * переключения вкладки, и снимок успевает раньше ответа.
 */
async function settled(page) {
  await page.waitForFunction(() => !document.body.innerText.includes('Загружаем'), {
    timeout: 10_000,
  })
  await wait(250)
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
  await wait(350)
}

/** На экране ввода выбираем сумму и категорию — пустая форма ничего не показывает. */
async function pickCategory(page) {
  await page.type('.amount-input', '1290')
  await clickByText(page, '.chip', 'Продукты')
  await wait(250)
}

async function openEditSheet(page) {
  await page.waitForSelector('.row--tappable')
  await page.click('.row--tappable')
  await page.waitForSelector('.sheet')
  await wait(450)
}

async function openCategories(page) {
  await clickByText(page, '.btn', 'Категории')
  await page.waitForSelector('.icon-btn')
  await wait(400)
}

/**
 * Открывает панель удаления категории — но ничего не удаляет.
 *
 * Снимок делается на живом демо, и подтверждение стёрло бы половину журнала:
 * следующий запуск скрипта получил бы уже другие данные.
 */
async function openDeletePanel(page) {
  await openCategories(page)
  const button = await page.evaluateHandle(() => {
    const card = [...document.querySelectorAll('.card--tight')].find((item) =>
      item.textContent.includes('Транспорт'),
    )
    return [...card.querySelectorAll('.icon-btn')].find((item) => item.title === 'Удалить')
  })
  await button.asElement().click()
  await page.waitForSelector('.btn--destructive')
  await wait(500)
}

async function applyTheme(page, theme) {
  await page.evaluate(
    (vars, scheme) => {
      const root = document.documentElement
      root.dataset.scheme = scheme
      for (const [key, value] of Object.entries(vars)) {
        root.style.setProperty(`--tg-${key}`, value)
      }
      document.body.style.colorScheme = scheme
    },
    THEMES[theme],
    theme,
  )
  await wait(120)
}

async function shoot(browser, theme, { name, tab, prepare }) {
  const page = await browser.newPage()
  await page.setViewport(VIEWPORT)

  await page.goto(BASE, { waitUntil: 'networkidle0' })
  await page.waitForSelector('.tabbar', { timeout: 10_000 })
  // Тему ставим после загрузки, а не до: приложение при старте само записывает
  // палитру Telegram в те же переменные и затёрло бы всё, что подсунуто заранее
  await applyTheme(page, theme)

  if (tab !== 'Добавить') await clickByText(page, '.tabbar button', tab)
  await settled(page)
  if (prepare) await prepare(page)
  await wait(300)

  const file = path.join(OUT, theme === 'dark' ? `${name}-dark.png` : `${name}.png`)
  await page.screenshot({ path: file })
  console.log(`  ${path.relative(process.cwd(), file)}`)
  await page.close()
}

const browser = await puppeteer.launch({
  executablePath: CHROME,
  args: ['--hide-scrollbars', '--force-color-profile=srgb'],
})

try {
  await mkdir(OUT, { recursive: true })
  for (const theme of Object.keys(THEMES)) {
    console.log(`${theme}:`)
    for (const shot of SHOTS) {
      await shoot(browser, theme, shot)
    }
  }
} finally {
  await browser.close()
}
