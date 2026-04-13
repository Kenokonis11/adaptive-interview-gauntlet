"""Backward-compatible re-exports for Judge wrappers."""

from src.agents.judge import run_question_judge, run_session_judge

__all__ = ["run_question_judge", "run_session_judge"]
