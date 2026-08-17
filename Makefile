.DEFAULT_GOAL := help
PY := backend/.venv/bin/python
PIP := backend/.venv/bin/pip

# Демо живёт в своей базе и со своими настройками, чтобы не задеть рабочую.
# Переменные окружения перекрывают .env, поэтому личный .env в корне не мешает.
DEMO_ENV := \
	DATABASE_URL=sqlite+aiosqlite:///$(CURDIR)/data/demo.db \
	STATIC_DIR=$(CURDIR)/frontend/dist \
	PUBLIC_URL=http://localhost:8000 \
	BOT_MODE=off SHEETS_ENABLED=false \
	DEV_AUTH_BYPASS=true DEV_TELEGRAM_ID=900000001 \
	ALLOWED_TELEGRAM_IDS=900000001,900000002 \
	JWT_SECRET=demo-only-not-a-real-secret LOG_LEVEL=WARNING

help: ## Показать список команд
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

setup: ## Поставить зависимости бэкенда и фронта
	python3 -m venv backend/.venv
	$(PIP) install -q -e "backend[dev]"
	cd frontend && npm install

migrate: ## Накатить миграции
	cd backend && .venv/bin/alembic upgrade head

revision: ## Создать миграцию: make revision m="что изменилось"
	cd backend && .venv/bin/alembic revision --autogenerate -m "$(m)"

api: ## Запустить бэкенд локально (http://localhost:8000)
	cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000

web: ## Запустить фронт локально (http://localhost:5173)
	cd frontend && npm run dev

test: ## Прогнать тесты
	cd backend && .venv/bin/pytest -q

lint: ## Проверить стиль бэкенда
	cd backend && .venv/bin/ruff check app tests

build: ## Собрать фронт в frontend/dist
	cd frontend && npm run build

demo: demo-build ## Демо на http://localhost:8000 — готовый журнал за 3 месяца, без Telegram
	@echo
	@echo "  Демо: http://localhost:8000  (Ctrl+C — остановить)"
	@echo "  Вы входите как Аня; второй участник — Борис."
	@echo
	@cd backend && $(DEMO_ENV) .venv/bin/uvicorn app.main:app --port 8000 --no-access-log

demo-build: ## Собрать фронт и пересоздать демо-базу, не запуская сервер
	@test -x backend/.venv/bin/python || { echo "Сначала: make setup"; exit 1; }
	@mkdir -p data
	@cd frontend && npm install --silent --no-audit --no-fund && npm run build
	@cd backend && $(DEMO_ENV) .venv/bin/alembic upgrade head >/dev/null
	@cd backend && $(DEMO_ENV) .venv/bin/python -m app.demo --reset

demo-docker: ## То же самое в докере — если нет локальных Python и Node
	docker compose -f docker-compose.demo.yml --profile build run --rm frontend
	docker compose -f docker-compose.demo.yml up --build

data: ## Подготовить каталог данных под пользователя контейнера (нужен sudo)
	mkdir -p data
	sudo chown -R 10001:10001 data

up: ## Поднять всё в docker: приложение + свой Caddy (нужны свободные порты 80 и 443)
	mkdir -p data
	docker compose --profile build run --rm frontend
	docker compose up -d --build

up-proxy: ## Поднять только приложение на 127.0.0.1 — когда 80/443 занял чужой веб-сервер
	mkdir -p data
	docker compose --profile build run --rm frontend
	docker compose -f docker-compose.yml -f docker-compose.behind-proxy.yml up -d --build app

up-shared: check-proxy-net ## Поднять приложение в сети чужого прокси-контейнера (нужен PROXY_NETWORK в .env)
	mkdir -p data
	docker compose --profile build run --rm frontend
	docker compose -f docker-compose.yml -f docker-compose.shared-net.yml up -d --build app

check-sheets: ## Проверить доступ к Google Sheets (в запущенном контейнере)
	docker compose exec -T app python -m app.sync.check

check-settle: ## Показать, из каких операций сложился долг во «Взаиморасчётах»
	docker compose exec -T app python -m app.repair

fix-settle: ## Пересчитать доли у операций, помеченных как проблемные
	docker compose exec -T app python -m app.repair --apply

check-proxy-net: ## Проверить, что сеть из PROXY_NETWORK существует
	@net=$$(grep -E '^PROXY_NETWORK=' .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"'\''' | tr -d '\r'); \
	if [ -z "$$net" ]; then \
		echo "В .env не задан PROXY_NETWORK — имя docker-сети, в которой работает ваш прокси."; \
	elif docker network inspect "$$net" >/dev/null 2>&1; then \
		echo "Сеть $$net найдена."; exit 0; \
	else \
		echo "Сеть '$$net' не существует."; \
	fi; \
	echo; echo "Доступные сети:"; docker network ls --format '  {{.Name}}'; \
	echo; echo "Впишите нужную строкой PROXY_NETWORK=<имя> в .env"; exit 1

down: ## Остановить docker
	docker compose down

logs: ## Логи приложения
	docker compose logs -f app

.PHONY: help setup migrate revision api web test lint build demo demo-build demo-docker data up up-proxy up-shared check-sheets check-settle fix-settle check-proxy-net down logs
