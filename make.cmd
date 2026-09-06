@echo off
set PYTHON=python
if "%1"=="run" (
    %PYTHON% scripts/make_submission.py --data ./data
) else if "%1"=="train" (
    %PYTHON% scripts/train.py --data ./data --candidate v0002
) else if "%1"=="predict" (
    %PYTHON% scripts/predict.py --data ./data
) else if "%1"=="promote" (
    %PYTHON% scripts/promote.py --candidate v0002
) else if "%1"=="rollback" (
    %PYTHON% scripts/rollback.py
) else if "%1"=="test" (
    %PYTHON% -m pytest tests/
) else if "%1"=="drift" (
    %PYTHON% scripts/check_drift.py --data ./data
) else if "%1"=="frontend" (
    %PYTHON% frontend/server.py --port 8080
) else (
    %PYTHON% scripts/make_submission.py --data ./data
)
