# Makefile for Smart Industrial Energy Monitoring System

PYTHON := .venv/Scripts/python.exe
PYTEST := .venv/Scripts/pytest.exe

.PHONY: help up down backfill train test experiment sim api dashboard

help:
	@echo "Available make commands:"
	@echo "  make up          - Start all 7 services via Docker Compose"
	@echo "  make down        - Stop all running Docker containers"
	@echo "  make backfill    - Generate 60 days of telemetry history"
	@echo "  make train       - Train Isolation Forest and LightGBM models"
	@echo "  make test        - Run complete pytest test suite (23 tests)"
	@echo "  make experiment  - Run Phase 9 Before/After optimization experiment"
	@echo "  make sim         - Run machine telemetry simulator locally"
	@echo "  make api         - Start FastAPI backend server on :8000"
	@echo "  make dashboard   - Launch Streamlit interactive dashboard on :8501"

up:
	docker compose up -d

down:
	docker compose down

backfill:
	$(PYTHON) scripts/backfill.py --days 60 --interval 15

train:
	$(PYTHON) scripts/train_models.py

test:
	$(PYTEST) tests/ -v

experiment:
	$(PYTHON) scripts/experiment.py

sim:
	$(PYTHON) -m simulator.main --speedup 1.0

api:
	$(PYTHON) -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

dashboard:
	$(PYTHON) -m streamlit run dashboard/app.py --server.port 8501
