"""Restricted Python execution helpers for MCP tool calls."""

from __future__ import annotations

import ast
import builtins
import contextlib
import io
import json
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any


BLOCKED_IMPORTS = {"requests", "urllib", "socket"}
WRITE_MODES = {"w", "a", "x", "+"}
ROOT_DIR = Path(__file__).resolve().parents[2]


def _build_result(
    exit_code: int,
    tests_passed: int,
    tests_total: int,
    results: list[dict[str, Any]],
    execution_time_ms: float,
    stdout: str = "",
    stderr: str = "",
) -> dict[str, Any]:
    return {
        "exit_code": exit_code,
        "tests_passed": tests_passed,
        "tests_total": tests_total,
        "results": results,
        "execution_time_ms": execution_time_ms,
        "stdout": stdout,
        "stderr": stderr,
    }


def _is_write_mode(node: ast.Call) -> bool:
    if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
        mode = node.args[1].value
        return any(flag in mode for flag in WRITE_MODES)

    for keyword in node.keywords:
        if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
            mode = keyword.value.value
            return any(flag in mode for flag in WRITE_MODES)

    return False


def _scan_python_security(tree: ast.AST) -> list[str]:
    violations: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_name = alias.name.split(".")[0]
                if root_name in BLOCKED_IMPORTS:
                    violations.append(f"Blocked import: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module_name = (node.module or "").split(".")[0]
            if module_name in BLOCKED_IMPORTS:
                violations.append(f"Blocked import: {node.module}")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "open" and _is_write_mode(node):
                violations.append("Blocked file write via open(..., mode)")

    return violations


def _safe_import(name: str, globals_: dict[str, Any] | None = None, locals_: dict[str, Any] | None = None, fromlist: tuple[Any, ...] = (), level: int = 0) -> Any:
    root_name = name.split(".")[0]
    if root_name in BLOCKED_IMPORTS:
        raise ImportError(f"Import of '{name}' is blocked in the sandbox.")
    return __import__(name, globals_, locals_, fromlist, level)


def _safe_open(file: str | bytes | int, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
    if any(flag in mode for flag in WRITE_MODES):
        raise PermissionError("File writes are blocked in the sandbox.")
    return open(file, mode, *args, **kwargs)


def _safe_builtins() -> dict[str, Any]:
    allowed_names = [
        "__build_class__",
        "__import__",
        "AttributeError",
        "Exception",
        "KeyError",
        "PermissionError",
        "TypeError",
        "ValueError",
        "abs",
        "all",
        "any",
        "bool",
        "dict",
        "enumerate",
        "filter",
        "float",
        "int",
        "isinstance",
        "len",
        "list",
        "map",
        "max",
        "min",
        "print",
        "range",
        "reversed",
        "round",
        "set",
        "sorted",
        "str",
        "sum",
        "tuple",
        "zip",
    ]
    builtins_dict = {name: getattr(builtins, name) for name in allowed_names}
    builtins_dict["__import__"] = _safe_import
    builtins_dict["open"] = _safe_open
    return builtins_dict


def _run_python_test_local(code: str) -> dict[str, Any]:
    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()
    namespace: dict[str, Any] = {"__builtins__": _safe_builtins()}
    try:
        with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
            try:
                namespace["__name__"] = "__main__"
                exec(code, namespace, namespace)
                return {
                    "passed": True,
                    "stdout": stdout_buffer.getvalue(),
                    "stderr": stderr_buffer.getvalue(),
                    "error_type": None,
                    "traceback": None,
                }
            except Exception as exc:  # pragma: no cover - exercised via subprocess
                return {
                    "passed": False,
                    "stdout": stdout_buffer.getvalue(),
                    "stderr": stderr_buffer.getvalue(),
                    "error_type": type(exc).__name__,
                    "traceback": traceback.format_exc(),
                }
    except Exception as exc:  # pragma: no cover - defensive subprocess wrapper
        return {
            "passed": False,
            "stdout": stdout_buffer.getvalue(),
            "stderr": f"{stderr_buffer.getvalue()}\n{exc}".strip(),
            "error_type": type(exc).__name__,
            "traceback": traceback.format_exc(),
        }

def _execute_with_timeout(code: str, timeout_seconds: int) -> dict[str, Any]:
    payload = json.dumps({"code": code})
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "src.mcp.executor", "--run-test"],
            input=payload,
            text=True,
            capture_output=True,
            cwd=str(ROOT_DIR),
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "timed_out": True,
            "passed": False,
            "stdout": "",
            "stderr": f"Execution timed out after {timeout_seconds} seconds.",
            "error_type": "TimeoutError",
            "traceback": None,
        }

    if completed.returncode != 0:
        return {
            "timed_out": False,
            "passed": False,
            "stdout": completed.stdout,
            "stderr": completed.stderr or f"Execution process exited unexpectedly with code {completed.returncode}.",
            "error_type": "ExecutionError",
            "traceback": None,
        }

    try:
        run_result = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {
            "timed_out": False,
            "passed": False,
            "stdout": completed.stdout,
            "stderr": completed.stderr or "Execution failed without returning a valid JSON payload.",
            "error_type": "ExecutionError",
            "traceback": None,
        }

    run_result["timed_out"] = False
    return run_result


def execute_python_with_tests(user_code: str, test_cases: list[dict], timeout_seconds: int = 10) -> dict[str, Any]:
    """Execute candidate Python code against hidden tests with basic sandboxing."""

    start_time = time.perf_counter()
    tests_total = len(test_cases)
    results: list[dict[str, Any]] = []
    tests_passed = 0
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []

    try:
        tree = ast.parse(user_code)
    except SyntaxError as exc:
        execution_time_ms = (time.perf_counter() - start_time) * 1000
        return _build_result(
            exit_code=3,
            tests_passed=0,
            tests_total=tests_total,
            results=[],
            execution_time_ms=execution_time_ms,
            stderr=f"SyntaxError: {exc}",
        )

    violations = _scan_python_security(tree)
    if violations:
        execution_time_ms = (time.perf_counter() - start_time) * 1000
        return _build_result(
            exit_code=3,
            tests_passed=0,
            tests_total=tests_total,
            results=[],
            execution_time_ms=execution_time_ms,
            stderr="; ".join(violations),
        )

    for test_case in test_cases:
        test_id = test_case.get("test_id", "unnamed_test")
        setup_code = test_case.get("setup_code", "")
        assertion_code = test_case.get("assertion_code", "")
        combined_code = "\n".join([setup_code, user_code, assertion_code])

        run_result = _execute_with_timeout(combined_code, timeout_seconds)
        stdout_chunks.append(run_result.get("stdout", ""))
        if run_result.get("stderr"):
            stderr_chunks.append(run_result["stderr"])

        test_result = {
            "test_id": test_id,
            "passed": run_result["passed"],
            "error_type": run_result.get("error_type"),
            "traceback": run_result.get("traceback"),
        }
        results.append(test_result)

        if run_result.get("timed_out"):
            # Abort remaining tests on timeout — no point continuing
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            return _build_result(
                exit_code=2,
                tests_passed=tests_passed,
                tests_total=tests_total,
                results=results,
                execution_time_ms=execution_time_ms,
                stdout="".join(stdout_chunks),
                stderr="\n".join(filter(None, stderr_chunks)),
            )

        if run_result["passed"]:
            tests_passed += 1
        # No early exit on failure — run all 5 tests so the UI can show a full pass/fail grid

    execution_time_ms = (time.perf_counter() - start_time) * 1000
    return _build_result(
        exit_code=0,
        tests_passed=tests_passed,
        tests_total=tests_total,
        results=results,
        execution_time_ms=execution_time_ms,
        stdout="".join(stdout_chunks),
        stderr="\n".join(filter(None, stderr_chunks)),
    )


def _cli_run_test() -> int:
    payload = json.load(sys.stdin)
    result = _run_python_test_local(payload.get("code", ""))
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--run-test":
        raise SystemExit(_cli_run_test())
