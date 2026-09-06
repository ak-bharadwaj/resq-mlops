# RESQ-MLOps Canonical Makefile

PYTHON ?= python

.PHONY: help run train predict promote rollback test drift clean frontend

help:
	@echo "Available commands:"
	@echo "  make run        - Reviewer P0 entry point: verify data contracts and gateway eligibility foundation"
	@echo "  make train      - Construct and evaluate candidate model v0002"
	@echo "  make predict    - Run predictions for active model"
	@echo "  make promote    - Run frozen promotion gate evaluation"
	@echo "  make rollback   - Reversible atomic rollback demonstration"
	@echo "  make test       - Run test suite"
	@echo "  make drift      - Run structural schema drift check"
	@echo "  make frontend   - Launch RESQ Operations Console web dashboard"

run:
	$(PYTHON) scripts/make_submission.py --data ./data

train:
	$(PYTHON) scripts/train.py --data ./data --candidate v0002

predict:
	$(PYTHON) scripts/predict.py --data ./data

promote:
	$(PYTHON) scripts/promote.py --candidate v0002

rollback:
	$(PYTHON) scripts/rollback.py

test:
	$(PYTHON) -m pytest tests/

drift:
	$(PYTHON) scripts/check_drift.py --data ./data

frontend:
	$(PYTHON) frontend/server.py --port 8080

