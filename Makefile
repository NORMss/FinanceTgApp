.DEFAULT_GOAL := help
PY := backend/.venv/bin/python
PIP := backend/.venv/bin/pip

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

up: ## Поднять всё в docker (прод)
	docker compose --profile build run --rm frontend
	docker compose up -d --build

down: ## Остановить docker
	docker compose down

logs: ## Логи приложения
	docker compose logs -f app

.PHONY: help setup migrate revision api web test lint build up down logs
