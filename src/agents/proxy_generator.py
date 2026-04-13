"""Proxy Generator agent — creates executable test proxies and mock datasets from extracted skills."""

from __future__ import annotations

import ast
import logging
from pydantic import BaseModel, ConfigDict, Field

from src.agents._runtime import run_structured
from src.agents.schemas import ExtractedSkill

logger = logging.getLogger(__name__)


class GeneratedProxy(BaseModel):
    """LLM output schema for a single generated proxy."""

    model_config = ConfigDict(extra="forbid")

    original_skill: str
    proxy_type: str = Field(description="One of: python_pandas, sql_duckdb, python_general, conceptual")
    proxy_context: str = Field(description="A concrete scenario prompt the Hiring Manager will use to ask a question.")
    test_dataset: str = Field(
        description="For python_*: Python setup code that creates test data. "
        "For sql_duckdb: CREATE TABLE + INSERT INTO statements. "
        "For conceptual: leave empty."
    )
    difficulty_default: str = "standard"


class GeneratedProxyList(BaseModel):
    """LLM output: list of proxies for all extracted skills."""

    model_config = ConfigDict(extra="forbid")

    proxies: list[GeneratedProxy]


PROXY_GENERATOR_PROMPT = """You are a Proxy Generator for a technical learning platform.

You receive a list of extracted skills from a job description. For each skill, create a test proxy.

== CRITICAL: proxy_context must be ULTRA-SPECIFIC ==

The proxy_context is what the Hiring Manager reads to formulate the practice question.
Vague proxy_context = vague questions = useless practice. Be precise.

For executable_python skills (proxy_type: "python_pandas" or "python_general"):
  proxy_context MUST include:
  1. The EXACT function signature:
     def function_name(param1: type, param2: type) -> return_type
  2. DataFrame/data schemas with column names and dtypes:
     df: columns user_id (int), revenue (float, some NaN), category (str)
  3. A numbered list of hard requirements the hidden tests will check:
     1. LEFT join on 'user_id' — all activity rows must survive
     2. Do NOT drop NaN values in the 'revenue' column
     3. Return the merged DataFrame — no prints, no side effects
  4. A brief note on edge cases the tests include (e.g., duplicate keys, nulls, empty input).

For executable_sql skills (proxy_type: "sql_duckdb"):
  proxy_context MUST include:
  1. The exact table schema: table_name (column DTYPE, column DTYPE)
  2. The exact column aliases the result must have (e.g., rolling_7day_avg, not avg_minutes)
  3. Any required SQL clauses (PARTITION BY, ORDER BY, frame spec like ROWS BETWEEN 6 PRECEDING AND CURRENT ROW)
  4. A numbered list of hard requirements the tests check.

For conceptual skills (proxy_type: "conceptual") — JS, React, statistics, system design, cloud, etc.:
  proxy_context MUST include:
  1. A realistic scenario (2-3 sentences) grounded in the job context.
  2. A numbered list of specific concepts the candidate must address in their response.
  3. Example: "Explain how you would implement debouncing in a React search component.
     Your answer must cover: (1) why debouncing is needed, (2) the useEffect/useCallback pattern,
     (3) how to choose the delay value, (4) how to handle the cleanup function."

== test_dataset rules ==

For python_pandas / python_general:
  Write valid Python that creates realistic test data (3-6 rows).
  Must include at least one NULL/NaN and one edge case (duplicate key, empty string, etc.).
  Example:
    import pandas as pd
    df = pd.DataFrame({'user_id': [1, 2, 3, 2], 'revenue': [100.0, None, 300.0, 150.0]})

For sql_duckdb:
  Write valid DuckDB DDL (CREATE TABLE + INSERT INTO). 3-6 rows, at least one NULL.
  Example:
    CREATE TABLE sessions (user_id INT, dt DATE, minutes FLOAT);
    INSERT INTO sessions VALUES (1, '2024-01-01', 30.0), (1, '2024-01-02', NULL);

For conceptual: set test_dataset to an empty string "".

== proxy_type mapping ==
  executable_python with DataFrames → "python_pandas"
  executable_python without DataFrames → "python_general"
  executable_sql → "sql_duckdb"
  conceptual (everything else) → "conceptual"

difficulty_default: "standard" for most skills, "warm_up" for entry-level, "stretch" for senior.

Return valid JSON matching the GeneratedProxyList schema.
"""


def run_proxy_generator(skills: list[ExtractedSkill]) -> list:
    """Generate validated SkillProxy objects from extracted skills."""

    from src.graph.state import SkillProxy  # Lazy import to avoid circular dependency

    skills_payload = "\n".join(
        f"- {s.skill_name} (category: {s.category}): {s.context_from_jd}" for s in skills
    )

    result = run_structured(
        PROXY_GENERATOR_PROMPT,
        f"Generate proxies for these skills:\n{skills_payload}",
        GeneratedProxyList,
    )

    validated: list[SkillProxy] = []
    for proxy in result.proxies:
        # Normalize proxy_type
        proxy_type = _normalize_proxy_type(proxy.proxy_type, proxy.original_skill, skills)
        difficulty = proxy.difficulty_default if proxy.difficulty_default in ("warm_up", "standard", "stretch") else "standard"

        # Dry-run validation for executable proxies
        dataset = proxy.test_dataset or ""
        if proxy_type in ("python_pandas", "python_general") and dataset:
            if not _validate_python_dataset(dataset):
                logger.warning("Invalid Python dataset for skill '%s', clearing dataset.", proxy.original_skill)
                dataset = ""
        elif proxy_type == "sql_duckdb" and dataset:
            if not _validate_sql_dataset(dataset):
                logger.warning("Invalid SQL dataset for skill '%s', clearing dataset.", proxy.original_skill)
                dataset = ""

        validated.append(
            SkillProxy(
                original_skill=proxy.original_skill,
                proxy_type=proxy_type,
                proxy_context=proxy.proxy_context,
                test_dataset=dataset,
                difficulty_default=difficulty,
            )
        )

    return validated


def _normalize_proxy_type(raw_type: str, skill_name: str, skills: list[ExtractedSkill]) -> str:
    """Map the LLM's proxy_type string to a valid SkillProxy literal."""

    normalized = raw_type.strip().lower()
    valid_types = {"python_pandas", "sql_duckdb", "python_general", "conceptual"}
    if normalized in valid_types:
        return normalized

    # Fallback: look at the original skill category
    for skill in skills:
        if skill.skill_name == skill_name:
            if skill.category == "executable_python":
                return "python_general"
            if skill.category == "executable_sql":
                return "sql_duckdb"
            return "conceptual"

    return "python_general"


def _validate_python_dataset(code: str) -> bool:
    """Validate that Python dataset setup code is syntactically valid."""

    try:
        ast.parse(code)
        return True
    except SyntaxError:
        return False


def _validate_sql_dataset(ddl: str) -> bool:
    """Validate that SQL DDL is executable in DuckDB."""

    try:
        import duckdb

        conn = duckdb.connect(":memory:")
        conn.execute(ddl)
        conn.close()
        return True
    except Exception:
        return False
