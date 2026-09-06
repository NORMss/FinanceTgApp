import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { retryDelay, retryTransient } from './api'
import App from './App'
import './styles.css'
import { initTelegram } from './telegram'

initTelegram()

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Данные меняем только мы вдвоём, поэтому агрессивный рефетч не нужен —
      // это экономит и батарею, и трафик на мобильном
      staleTime: 30_000,
      retry: retryTransient,
      retryDelay,
      refetchOnWindowFocus: false,
    },
    // Мутации не повторяем: прокси не различает «не дозвонился» и «дозвонился,
    // но ответ потерялся», а вторая попытка создать трату — это трата-дубль
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
)
