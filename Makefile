PYTHON ?= python
PYTHONPATH := src

.PHONY: dev test cov eval

dev:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m uvicorn everrag.main:app --reload --port 8000

test:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m pytest

cov:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m pytest --cov=everrag --cov-report=term-missing

eval:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m eval.run_eval
