.PHONY: demo run collect test lint enrich

PYTHON ?= python3
VENV ?= .venv
BIN := $(VENV)/bin

$(BIN)/python:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install -e ".[dev]"

demo: $(BIN)/python
	$(BIN)/python -m devin_kpi demo-data

run:
	$(BIN)/streamlit run devin_kpi/app/Home.py --server.headless true

collect:
	$(BIN)/python -m devin_kpi collect --since 90d

enrich:
	$(BIN)/python -m devin_kpi enrich

test:
	$(BIN)/pytest -q

lint:
	$(BIN)/ruff check . && $(BIN)/ruff format --check .
