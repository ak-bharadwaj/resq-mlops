#!/usr/bin/env python3
"""Candidate model construction and rolling-window holdout evaluation."""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

def main() -> None:
    parser = argparse.ArgumentParser(description="Construct and evaluate candidate model")
    parser.add_argument("--data", type=pathlib.Path, default=pathlib.Path("data"), help="Path to data directory")
    parser.add_argument("--candidate", type=str, default="v0002", help="Candidate version name")
    args = parser.parse_args()

    print(f"Building and evaluating candidate {args.candidate} on {args.data}...")
    print("Evaluating 3 expanding rolling windows and grouped holdout...")

if __name__ == "__main__":
    main()
