"""Client helpers for calling the local MCP server over stdio."""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any

import anyio
from anyio import fail_after
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


ROOT_DIR = Path(__file__).resolve().parents[2]


async def _call_tool_async(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        json.dumps(arguments)
    except Exception as exc:
        return _graceful_failure("MCP payload could not be serialized for subprocess transport.", exc)

    try:
        server = StdioServerParameters(
            command=sys.executable,
            args=["-m", "src.mcp.server"],
            cwd=ROOT_DIR,
            env=dict(os.environ),
        )

        with fail_after(5):
            async with stdio_client(server) as (read_stream, write_stream):
                session = ClientSession(read_stream, write_stream)
                async with session:
                    with fail_after(5):
                        await session.initialize()
                    with fail_after(15):
                        result = await session.call_tool(tool_name, arguments=arguments)

        if result.isError:
            raise RuntimeError(f"MCP tool '{tool_name}' returned an error: {result.content}")

        if result.structuredContent is not None and isinstance(result.structuredContent, dict):
            return result.structuredContent

        for item in result.content:
            text = getattr(item, "text", None)
            if text:
                try:
                    return json.loads(text)
                except Exception:
                    continue

        raise RuntimeError(f"MCP tool '{tool_name}' did not return structured content.")
    except TimeoutError as exc:
        return _graceful_failure("MCP subprocess timed out during execution.", exc)
    except Exception as exc:
        return _graceful_failure("MCP subprocess crashed during execution.", exc)


def call_mcp_tool(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Call a local MCP tool through a subprocess-backed stdio client."""

    return anyio.run(_call_tool_async, tool_name, arguments)


def _graceful_failure(message: str, exc: Exception) -> dict[str, Any]:
    return {
        "exit_code": 3,
        "tests_passed": 0,
        "tests_total": 0,
        "results": [],
        "execution_time_ms": 0.0,
        "stdout": "",
        "stderr": f"{message} {exc}",
        "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
    }
