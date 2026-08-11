/**
 * Тонкая обёртка над window.Telegram.WebApp.
 *
 * Сознательно не тянем @telegram-apps/sdk: нам нужны initData, тема, haptics и MainButton —
 * это полсотни строк типов против лишней зависимости, которая ломает API между мажорками.
 * Официальный telegram-web-app.js подключён в index.html и стабилен годами.
 */

type ThemeParams = Record<string, string | undefined>

type HapticStyle = 'light' | 'medium' | 'heavy' | 'rigid' | 'soft'

interface TelegramWebApp {
  initData: string
  colorScheme: 'light' | 'dark'
  themeParams: ThemeParams
  isExpanded: boolean
  viewportStableHeight: number
  ready(): void
  expand(): void
  close(): void
  onEvent(event: string, handler: () => void): void
  offEvent(event: string, handler: () => void): void
  HapticFeedback?: {
    impactOccurred(style: HapticStyle): void
    notificationOccurred(type: 'error' | 'success' | 'warning'): void
  }
  BackButton?: { show(): void; hide(): void; onClick(cb: () => void): void; offClick(cb: () => void): void }
  showAlert?(message: string): void
}

declare global {
  interface Window {
    Telegram?: { WebApp?: TelegramWebApp }
  }
}

export const webApp = window.Telegram?.WebApp

/** true, когда приложение открыто вне Telegram — тогда работаем в dev-режиме. */
export const isStandalone = !webApp?.initData

export function initTelegram(): void {
  if (!webApp) return
  webApp.ready()
  webApp.expand()
  applyTheme()
  webApp.onEvent('themeChanged', applyTheme)
}

/** Переносим палитру Telegram в CSS-переменные, чтобы приложение выглядело родным. */
function applyTheme(): void {
  if (!webApp) return
  const root = document.documentElement
  root.dataset.scheme = webApp.colorScheme
  for (const [key, value] of Object.entries(webApp.themeParams)) {
    if (value) root.style.setProperty(`--tg-${key.replace(/_/g, '-')}`, value)
  }
}

export function haptic(style: HapticStyle = 'light'): void {
  webApp?.HapticFeedback?.impactOccurred(style)
}

export function notify(type: 'error' | 'success' | 'warning'): void {
  webApp?.HapticFeedback?.notificationOccurred(type)
}

export function getInitData(): string {
  return webApp?.initData ?? ''
}
