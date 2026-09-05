"""Unit tests for --data alternate path support across entry points."""
import pathlib
import subprocess
import sys


def test_make_submission_data_flag_help():
    result = subprocess.run(
        [sys.executable, "scripts/make_submission.py", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "--data" in result.stdout
    assert "Path to data directory" in result.stdout


def test_predict_data_flag_help():
    result = subprocess.run(
        [sys.executable, "scripts/predict.py", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "--data" in result.stdout
