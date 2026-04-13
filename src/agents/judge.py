"""Judge agent wrappers for per-question scoring and session synthesis."""

from __future__ import annotations

from src.agents._runtime import (
    dump_for_prompt,
    mastery_for_skill,
    normalize_proxies,
    normalize_question,
    run_structured,
    state_value,
)
from src.agents.schemas import QuestionScore, SessionReport


QUESTION_JUDGE_PROMPT = """You are an evaluation Judge. You assess candidate performance after each question.

Question asked: {question_text}
Expected concepts: {expected_concepts}
MCP result: tests passed {tests_passed} / {tests_total}
Execution time: {execution_time_ms}ms
Attempts taken: {attempt_count}
Hints used: {hints_used}

Score the candidate's performance on this skill from 0.0 to 1.0 using this rubric:
- 1.0: Passed all tests on first attempt, no hints, fast execution
- 0.8: Passed all tests on first attempt with one hint
- 0.6: Passed all tests on second attempt
- 0.4: Passed after reteach (simpler question)
- 0.2: Failed reteach question but showed partial understanding
- 0.0: Failed reteach question with no demonstrated understanding

Compute the mastery delta: new_score - {prior_mastery}

Return valid JSON:
{{
  "skill": "{current_skill}",
  "score": 0.0,
  "prior_mastery": {prior_mastery},
  "delta": 0.0,
  "narrative": "1-2 sentence explanation of performance"
}}
"""


CONCEPTUAL_JUDGE_PROMPT = """You are an evaluation Judge. You assess candidate performance on a CONCEPTUAL question.
This question was answered verbally — there is no code execution or test result.

Question asked: {question_text}
Expected concepts: {expected_concepts}
Candidate's response: {user_submission}
Attempts taken: {attempt_count}
Hints used: {hints_used}

Score the candidate from 0.0 to 1.0 using this rubric:
- 1.0: Comprehensive, accurate answer demonstrating deep understanding. No hints needed.
- 0.8: Mostly correct with minor gaps. Showed strong conceptual grasp.
- 0.6: Partially correct. Understood the basics but missed key nuances.
- 0.4: Showed some understanding but significant gaps or misconceptions.
- 0.2: Minimal understanding demonstrated.
- 0.0: No meaningful understanding shown.

Return valid JSON:
{{
  "skill": "{current_skill}",
  "score": 0.0,
  "prior_mastery": {prior_mastery},
  "delta": 0.0,
  "narrative": "1-2 sentence explanation of performance"
}}
"""


SESSION_JUDGE_PROMPT = """You are an evaluation Judge producing the end-of-session performance report.

Session transcript: {session_transcript}
All mastery deltas this session: {mastery_deltas}
Skills covered: {skills_covered}

Produce:
1. An overall session score (0.0 to 1.0), weighted average of skill scores
2. A 3-5 sentence narrative: what the candidate did well, what to focus on next session
3. The single highest-priority skill to study before the next session

Return valid JSON:
{{
  "session_score": 0.0,
  "narrative": "string",
  "top_priority_next_session": "skill name"
}}
"""


def _compute_score(
    tests_passed: int,
    tests_total: int,
    attempt_count: int,
    hints_used: int,
    consecutive_failures: int,
    execution_time_ms: float,
) -> float:
    ratio = 0.0 if tests_total == 0 else tests_passed / tests_total

    if consecutive_failures >= 1:
        if tests_passed == tests_total and attempt_count == 1:
            return round(0.45 * ratio, 3)
        if tests_passed == tests_total and attempt_count >= 2:
            return round(0.25 * ratio, 3)
        if tests_passed >= 3:
            return round(0.10 * ratio, 3)
        return 0.0

    if tests_passed == tests_total and attempt_count == 1 and hints_used == 0 and execution_time_ms <= 5000:
        return 1.0
    if tests_passed == tests_total and attempt_count == 1 and hints_used >= 1:
        return 0.85
    if tests_passed == tests_total and attempt_count == 1 and execution_time_ms > 5000:
        return 0.75
    if attempt_count == 2 and hints_used == 0:
        return round(0.65 * ratio, 3)
    if attempt_count == 2 and hints_used >= 1:
        return round(0.55 * ratio, 3)
    return 0.0


def run_question_judge(state_dict: dict) -> QuestionScore:
    """Run the per-question Judge with strict structured parsing.

    For conceptual skills (no MCP result), the LLM score is the final score.
    For executable skills, the deterministic _compute_score overrides the LLM.
    """

    question = normalize_question(state_value(state_dict, "current_question", default={}))
    current_skill = state_value(state_dict, "current_skill", default="")
    prior_mastery = mastery_for_skill(state_dict, current_skill)
    attempt_count = state_value(state_dict, "attempt_count", default=0)
    hints_used = state_value(state_dict, "hints_used", default=0)

    # Detect conceptual skill — no MCP result expected
    proxy = state_value(state_dict, "current_proxy", default=None)
    is_conceptual = False
    if proxy is not None:
        pt = proxy.proxy_type if hasattr(proxy, "proxy_type") else (proxy.get("proxy_type") if isinstance(proxy, dict) else None)
        is_conceptual = pt == "conceptual"

    if is_conceptual:
        user_submission = state_value(state_dict, "user_submission", default="") or ""
        prompt = CONCEPTUAL_JUDGE_PROMPT.format(
            question_text=question["text"],
            expected_concepts=dump_for_prompt(question["expected_concepts"]),
            user_submission=user_submission,
            attempt_count=attempt_count,
            hints_used=hints_used,
            prior_mastery=prior_mastery,
            current_skill=current_skill,
        )
        result = run_structured(prompt, "Score the conceptual response now.", QuestionScore)
        # For conceptual skills, the LLM's score IS the final score
        return QuestionScore(
            skill=result.skill or current_skill,
            score=result.score,
            prior_mastery=prior_mastery,
            delta=round(result.score - prior_mastery, 3),
            narrative=result.narrative,
        )

    # Executable skill path — deterministic scoring
    mcp_result = state_value(state_dict, "mcp_result", default={}) or {}
    tests_passed = getattr(mcp_result, "tests_passed", None) if not isinstance(mcp_result, dict) else mcp_result.get("tests_passed", 0)
    tests_total = getattr(mcp_result, "tests_total", None) if not isinstance(mcp_result, dict) else mcp_result.get("tests_total", 0)
    execution_time_ms = getattr(mcp_result, "execution_time_ms", None) if not isinstance(mcp_result, dict) else mcp_result.get("execution_time_ms", 0.0)
    consecutive_failures = state_value(state_dict, "consecutive_failures", default=0)
    deterministic_score = _compute_score(
        tests_passed=tests_passed or 0,
        tests_total=tests_total or 0,
        attempt_count=attempt_count,
        hints_used=hints_used,
        consecutive_failures=consecutive_failures,
        execution_time_ms=execution_time_ms or 0.0,
    )

    prompt = QUESTION_JUDGE_PROMPT.format(
        question_text=question["text"],
        expected_concepts=dump_for_prompt(question["expected_concepts"]),
        tests_passed=tests_passed or 0,
        tests_total=tests_total or 0,
        execution_time_ms=execution_time_ms or 0.0,
        attempt_count=attempt_count,
        hints_used=hints_used,
        prior_mastery=prior_mastery,
        current_skill=current_skill,
    )
    result = run_structured(prompt, "Score the question now.", QuestionScore)
    return QuestionScore(
        skill=result.skill or current_skill,
        score=deterministic_score,
        prior_mastery=prior_mastery,
        delta=round(deterministic_score - prior_mastery, 3),
        narrative=result.narrative,
    )


def run_session_judge(state_dict: dict) -> SessionReport:
    """Run the session-synthesis Judge with strict structured parsing."""

    proxy_list = normalize_proxies(state_value(state_dict, "skill_proxies", default=[]))
    skills_covered = [proxy.get("original_skill") or proxy.get("name") or "" for proxy in proxy_list]

    prompt = SESSION_JUDGE_PROMPT.format(
        session_transcript=dump_for_prompt(state_value(state_dict, "session_transcript", "transcript", default=[])),
        mastery_deltas=dump_for_prompt(state_value(state_dict, "mastery_deltas", default={})),
        skills_covered=dump_for_prompt(skills_covered),
    )
    return run_structured(prompt, "Produce the session report now.", SessionReport)
