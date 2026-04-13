"""Conditional routing helpers for the interview workflow."""

from __future__ import annotations

from src.graph.state import InterviewState


def route_human_input(state: InterviewState) -> str:
    """Route based on the learner's latest interaction.

    Conceptual skills bypass the QA/MCP pipeline entirely and go
    straight to the Judge for text-based evaluation.
    """

    event = state.get("submission_event")
    if event == "hint":
        return "deliver_hint"
    if event == "timeout":
        return "reteach"

    # Check if current skill is conceptual — skip sandbox
    proxy = state.get("current_proxy")
    if proxy is not None:
        proxy_type = proxy.proxy_type if hasattr(proxy, "proxy_type") else proxy.get("proxy_type")
        if proxy_type == "conceptual":
            return "run_judge"

    return "run_qa_engineer"


def route_after_question(state: InterviewState) -> str:
    """End the session cleanly if no more skills remain after asking."""

    if state.get("session_complete"):
        return "end_session"
    return "receive_submission"


def evaluate_result(state: InterviewState) -> str:
    """Route based on the populated MCP result and retry count."""

    result = state.get("mcp_result")
    exit_code = result.exit_code if result is not None else 1

    if exit_code == 0:
        return "run_judge"

    attempt_count = int(state.get("attempt_count", 0))
    if attempt_count < 2:
        return "deliver_feedback"
    return "reteach"


def route_after_judge(state: InterviewState) -> str:
    """Continue interviewing until all prioritized skills are covered."""

    completed = set(state.get("mastery_deltas", {}).keys())
    prioritized = state.get("prioritized_skills", [])
    remaining = [skill for skill in prioritized if skill not in completed]
    if remaining:
        return "ask_question"
    return "end_session"
