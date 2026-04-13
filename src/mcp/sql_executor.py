"""DuckDB-backed SQL execution helpers for MCP tool calls."""

from __future__ import annotations

import json
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any


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


def _run_sql_validation_local(
    user_query: str,
    schema_setup: str,
    test_cases: list[dict[str, Any]],
) -> dict[str, Any]:
    import duckdb

    results: list[dict[str, Any]] = []
    tests_passed = 0

    try:
        conn = duckdb.connect(":memory:")
        try:
            conn.execute(schema_setup)
            conn.execute(f"CREATE VIEW candidate_result AS ({user_query})")
        except Exception as exc:
            return {
                "exit_code": 3,
                "tests_passed": 0,
                "results": [],
                "stderr": str(exc),
                "traceback": traceback.format_exc(),
            }

        for test_case in test_cases:
            test_id = test_case.get("test_id", "unnamed_test")
            validation_query = test_case.get("validation_query", "")
            try:
                rows = conn.execute(validation_query).fetchall()
                passed = bool(rows and rows[0] and rows[0][0])
                results.append(
                    {
                        "test_id": test_id,
                        "passed": passed,
                        "error_type": None if passed else "AssertionError",
                        "traceback": None if passed else f"Validation query returned falsy result for {test_id}.",
                    }
                )
                if not passed:
                    return {
                        "exit_code": 1,
                        "tests_passed": tests_passed,
                        "results": results,
                        "stderr": f"Validation failed for {test_id}.",
                        "traceback": None,
                    }
                tests_passed += 1
            except Exception as exc:
                results.append(
                    {
                        "test_id": test_id,
                        "passed": False,
                        "error_type": type(exc).__name__,
                        "traceback": traceback.format_exc(),
                    }
                )
                return {
                    "exit_code": 1,
                    "tests_passed": tests_passed,
                    "results": results,
                    "stderr": str(exc),
                    "traceback": traceback.format_exc(),
                }

        return {
            "exit_code": 0,
            "tests_passed": tests_passed,
            "results": results,
            "stderr": "",
            "traceback": None,
        }
    except Exception as exc:  # pragma: no cover - defensive subprocess wrapper
        return {
            "exit_code": 1,
            "tests_passed": tests_passed,
            "results": results,
            "stderr": str(exc),
            "traceback": traceback.format_exc(),
        }


def _execute_sql_with_timeout(
    user_query: str,
    schema_setup: str,
    test_cases: list[dict[str, Any]],
    timeout_seconds: int,
) -> dict[str, Any]:
    payload = json.dumps(
        {
            "user_query": user_query,
            "schema_setup": schema_setup,
            "test_cases": test_cases,
        }
    )
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "src.mcp.sql_executor", "--run-test"],
            input=payload,
            text=True,
            capture_output=True,
            cwd=str(ROOT_DIR),
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "exit_code": 2,
            "tests_passed": 0,
            "results": [],
            "stderr": f"Execution timed out after {timeout_seconds} seconds.",
            "traceback": None,
        }

    if completed.returncode != 0:
        return {
            "exit_code": 1,
            "tests_passed": 0,
            "results": [],
            "stderr": completed.stderr or f"Execution process exited unexpectedly with code {completed.returncode}.",
            "traceback": None,
        }

    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {
            "exit_code": 1,
            "tests_passed": 0,
            "results": [],
            "stderr": completed.stderr or "Execution failed without returning a valid JSON payload.",
            "traceback": None,
        }


def execute_sql_with_tests(
    user_query: str,
    schema_setup: str,
    test_cases: list[dict],
    timeout_seconds: int = 10,
) -> dict[str, Any]:
    """Execute candidate SQL against DuckDB and validate candidate_result."""

    start_time = time.perf_counter()
    tests_total = len(test_cases)
    run_result = _execute_sql_with_timeout(user_query, schema_setup, test_cases, timeout_seconds)
    execution_time_ms = (time.perf_counter() - start_time) * 1000

    return _build_result(
        exit_code=run_result["exit_code"],
        tests_passed=run_result.get("tests_passed", 0),
        tests_total=tests_total,
        results=run_result.get("results", []),
        execution_time_ms=execution_time_ms,
        stdout="",
        stderr=run_result.get("stderr", ""),
    )


def _cli_run_test() -> int:
    payload = json.load(sys.stdin)
    result = _run_sql_validation_local(
        payload.get("user_query", ""),
        payload.get("schema_setup", ""),
        payload.get("test_cases", []),
    )
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--run-test":
        raise SystemExit(_cli_run_test())
