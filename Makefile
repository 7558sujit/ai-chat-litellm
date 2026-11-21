.PHONY: up down test logs
up:
	@test -f .env || cp .env.example .env
	docker compose up --build -d
	@echo "Frontend: http://localhost:3000  Backend: http://localhost:8000/health"
down:
	docker compose down
test:
	cd backend && pip install -q -r requirements.txt && python -m pytest -q
logs:
	docker compose logs -f
