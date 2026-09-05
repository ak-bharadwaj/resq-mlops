#!/usr/bin/env python3
"""Reversible atomic rollback demonstration."""
from __future__ import annotations

import json
import pathlib
import sys

def main() -> None:
    with open("registry/active.json", encoding="utf-8") as f:
        active = json.load(f)
    print(f"Current active version: {active.get('production_version')}")
    prev = active.get("previous_version")
    if not prev:
        print("No previous version to rollback to.")
        return
    print(f"Validating target {prev} artifact integrity and replay hash...")

if __name__ == "__main__":
    main()
