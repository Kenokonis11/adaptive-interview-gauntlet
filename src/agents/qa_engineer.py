"""QA Engineer agent wrappers."""

from __future__ import annotations

from src.agents._runtime import current_proxy, dump_for_prompt, normalize_question, run_structured, state_value
from src.agents.schemas import QATestCases


QA_ENGINEER_PROMPT = """You are a QA Engineer. You write hidden unit tests. You never speak to the candidate.

Question that was asked: {question_text}
Skill being tested: {current_skill}
Expected concepts: {expected_concepts}
Test dataset available: {test_dataset}
Proxy type: {proxy_type}
Target MCP tool name: {tool_name}

Your job:
Generate exactly 5 unit test cases that:
1. Test the happy path (valid input, expected output)
2. Test null or missing value handling
3. Test edge case: empty input or single-row input
4. Test edge case: duplicate values or ties
5. Test performance-adjacent correctness: the result must have the correct grain or shape

For python_pandas and python_general proxies: return JSON for execute_python_with_tests.
For sql_duckdb proxies: return JSON for execute_sql_with_tests, including schema_setup.

Return ONLY valid JSON with:
- tool_name
- schema_setup (required for SQL, omitted for Python)
- test_cases
Do not include user_code or user_query; the graph supplies the candidate submission separately.
No explanation. No preamble.
"""


def run_qa(state_dict: dict) -> QATestCases:
    """Run the QA Engineer with strict structured parsing."""

    question = normalize_question(state_value(state_dict, "current_question", default={}))
    skill = state_value(state_dict, "current_skill", default="")
    proxy = current_proxy(state_dict)
    proxy_type = proxy.get("proxy_type", "python_general")
    tool_name = "execute_sql_with_tests" if proxy_type == "sql_duckdb" else "execute_python_with_tests"

    prompt = QA_ENGINEER_PROMPT.format(
        question_text=question["text"],
        current_skill=skill,
        expected_concepts=dump_for_prompt(question["expected_concepts"]),
        test_dataset=dump_for_prompt(proxy.get("test_dataset", "")),
        proxy_type=proxy_type,
        tool_name=tool_name,
    )
    return run_structured(prompt, "Generate the hidden test payload now.", QATestCases)
