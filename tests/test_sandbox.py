"""Contract tests for deterministic MCP execution helpers."""

from src.mcp.executor import execute_python_with_tests
from src.mcp.sql_executor import execute_sql_with_tests


def test_execute_python_with_tests_passes_simple_case():
    result = execute_python_with_tests(
        user_code="def add_one(x):\n    return x + 1",
        test_cases=[
            {
                "test_id": "test_add_one",
                "setup_code": "",
                "assertion_code": "assert add_one(2) == 3",
            }
        ],
    )

    assert result["exit_code"] == 0
    assert result["tests_passed"] == 1
    assert result["tests_total"] == 1


def test_execute_python_with_tests_blocks_network_imports():
    result = execute_python_with_tests(
        user_code="import requests\n\ndef solve():\n    return 1",
        test_cases=[],
    )

    assert result["exit_code"] == 3
    assert "Blocked import" in result["stderr"]


def test_execute_sql_with_tests_validates_candidate_result():
    result = execute_sql_with_tests(
        user_query="SELECT 1 AS value",
        schema_setup="CREATE TABLE sample (value INTEGER);",
        test_cases=[
            {
                "test_id": "test_value_present",
                "validation_query": "SELECT COUNT(*) = 1 FROM candidate_result WHERE value = 1",
                "description": "candidate_result contains the expected row",
            }
        ],
    )

    assert result["exit_code"] == 0
    assert result["tests_passed"] == 1
    assert result["tests_total"] == 1
