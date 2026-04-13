"""MCP stdio server exposing deterministic execution tools."""

from __future__ import annotations

from src.mcp.executor import execute_python_with_tests as run_python_tests
from src.mcp.sql_executor import execute_sql_with_tests as run_sql_tests

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover - depends on installed MCP SDK version
    FastMCP = None


if FastMCP is None:  # pragma: no cover - defensive import guard
    raise ImportError("FastMCP is not available from the installed MCP SDK.")


server = FastMCP("adaptive-interview-gauntlet")


@server.tool()
def execute_python_with_tests(
    user_code: str,
    test_cases: list[dict],
    timeout_seconds: int = 10,
) -> dict:
    """Run Python code against hidden tests in the deterministic sandbox."""

    return run_python_tests(
        user_code=user_code,
        test_cases=test_cases,
        timeout_seconds=timeout_seconds,
    )


@server.tool()
def execute_sql_with_tests(
    user_query: str,
    schema_setup: str,
    test_cases: list[dict],
    timeout_seconds: int = 10,
) -> dict:
    """Run SQL against DuckDB and validate candidate_result."""

    return run_sql_tests(
        user_query=user_query,
        schema_setup=schema_setup,
        test_cases=test_cases,
        timeout_seconds=timeout_seconds,
    )


if __name__ == "__main__":
    server.run(transport="stdio")
