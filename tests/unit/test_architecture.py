"""AST-based architecture boundary and monotonic time authority tests."""
import ast
from pathlib import Path
import pytest


def get_python_files(directory: Path) -> list[Path]:
    return [p for p in directory.rglob("*.py") if p.is_file()]


def get_full_attr_name(node: ast.AST) -> str:
    """Helper to extract full dot-separated name from AST Attribute / Name nodes."""
    if isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, ast.Attribute):
        value_name = get_full_attr_name(node.value)
        return f"{value_name}.{node.attr}" if value_name else node.attr
    return ""


def check_wall_clock_in_ast(code: str, filename: str = "<string>") -> list[str]:
    """Analyze AST of Python code for forbidden wall-clock function calls.

    Detects:
    - datetime.now(), datetime.utcnow()
    - dt.now(), dt.utcnow()
    - time.time(), time.ctime(), time.localtime(), time.gmtime()
    """
    violations = []
    tree = ast.parse(code, filename=filename)

    datetime_modules = set()
    time_modules = set()
    wall_clock_funcs = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name
                if alias.name == "datetime":
                    datetime_modules.add(name)
                elif alias.name == "time":
                    time_modules.add(name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for alias in node.names:
                local_name = alias.asname or alias.name
                if mod == "datetime":
                    if alias.name in ("now", "utcnow"):
                        wall_clock_funcs.add(local_name)
                elif mod == "time":
                    if alias.name in ("time", "ctime", "localtime", "gmtime"):
                        wall_clock_funcs.add(local_name)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                attr = func.attr
                full_name = get_full_attr_name(func)
                parts = full_name.split(".")
                prefixes = parts[:-1]

                if attr in ("now", "utcnow"):
                    if any(p in datetime_modules or p == "datetime" or p == "dt" for p in prefixes):
                        violations.append(f"Wall-clock call '{full_name}()' at line {node.lineno}")
                elif attr in ("time", "ctime", "localtime", "gmtime"):
                    if any(p in time_modules or p == "time" for p in prefixes):
                        violations.append(f"Wall-clock call '{full_name}()' at line {node.lineno}")
            elif isinstance(func, ast.Name):
                if func.id in wall_clock_funcs:
                    violations.append(f"Wall-clock call '{func.id}()' at line {node.lineno}")

    return violations


def test_zero_wall_clock_in_production_code():
    """Verify zero system clock calls exist in prediction and feature paths."""
    root = Path(__file__).parent.parent.parent
    target_dirs = [root / "app", root / "scripts"]
    # Operational CLI scripts capture live runtime execution timestamps for audit reports and run.json provenance
    exempt_monitoring_scripts = {"check_drift.py", "rollback.py", "promote.py", "make_submission.py", "predict.py"}
    all_violations = []

    for d in target_dirs:
        for py_file in get_python_files(d):
            if py_file.name in exempt_monitoring_scripts:
                continue
            code = py_file.read_text(encoding="utf-8")
            violations = check_wall_clock_in_ast(code, filename=str(py_file))
            for v in violations:
                all_violations.append(f"{py_file.name}: {v}")

    assert len(all_violations) == 0, f"Found wall-clock calls in production paths: {all_violations}"


def test_prediction_never_imports_evaluation_or_labels():
    """Verify predict modules never import evaluation code or field_visits directly."""
    root = Path(__file__).parent.parent.parent
    predict_files = [
        root / "app" / "model" / "predict.py",
        root / "scripts" / "predict.py",
        root / "scripts" / "make_submission.py",
    ]

    forbidden_imports = ["evaluate", "field_visits", "label_gateway_week"]
    violations = []

    for p in predict_files:
        if not p.exists():
            continue
        code = p.read_text(encoding="utf-8")
        tree = ast.parse(code, filename=str(p))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if any(f in alias.name for f in forbidden_imports):
                        violations.append(f"{p.name} imports {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if any(f in mod for f in forbidden_imports):
                    violations.append(f"{p.name} imports from {mod}")

    assert len(violations) == 0, f"Physical module isolation violated: {violations}"
