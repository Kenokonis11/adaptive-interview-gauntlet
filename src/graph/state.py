"""State definitions for the adaptive interview graph."""

from __future__ import annotations

from typing import Any, Literal, Optional, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from src.agents.schemas import QATestCases, QuestionScore


class MCPResult(BaseModel):
    """Represents the outcome of a deterministic MCP execution."""

    model_config = ConfigDict(extra="forbid")

    exit_code: int
    tests_passed: int = 0
    tests_total: int = 0
    execution_time_ms: float = 0.0
    stdout: str = ""
    stderr: str = ""
    traceback: Optional[str] = None
    results: list[dict[str, Any]] = Field(default_factory=list)


class SkillProxy(BaseModel):
    """A proxy task that lets the system assess a target skill."""

    model_config = ConfigDict(extra="forbid")

    original_skill: str
    proxy_type: Literal["python_pandas", "sql_duckdb", "python_general", "conceptual"]
    proxy_context: str
    test_dataset: str
    difficulty_default: Literal["warm_up", "standard", "stretch"] = "standard"


class Question(BaseModel):
    """The active interview question."""

    model_config = ConfigDict(extra="forbid")

    text: str
    skill: str
    difficulty: Literal["warm_up", "standard", "stretch"]
    expected_concepts: list[str] = Field(default_factory=list)


class InterviewState(TypedDict, total=False):
    """Shared mutable state passed between LangGraph nodes."""

    # Intake form fields (provided by user before graph starts)
    provided_company: str
    provided_role: str
    raw_job_description: str
    user_experience_needs: str

    job_yaml_path: str
    target_company: str
    target_role: str
    session_id: str

    mastery: dict[str, float]
    job_requirements: list[str]
    study_guide: str
    skill_proxies: list[SkillProxy]

    current_question: Optional[Question]
    current_skill: str
    previous_questions: list[str]
    user_submission: Optional[str]
    submission_event: Optional[Literal["hint", "timeout", "submission"]]
    attempt_count: int
    consecutive_failures: int
    mcp_result: Optional[MCPResult]
    session_transcript: list[dict[str, str]]

    mastery_deltas: dict[str, float]
    session_score: float
    judge_narrative: str

    mastery_alpha: float
    mastery_file_path: str
    mastery_full_data: dict[str, Any]
    prioritized_skills: list[str]
    hints_used: int
    pending_tests: Optional[QATestCases]
    latest_question_score: Optional[QuestionScore]
    guide_action: Optional[str]
    current_proxy: Optional[SkillProxy]
    top_priority_next_session: Optional[str]
    question_history: list[Question]
    reuse_current_question: bool
    error_message: Optional[str]
    session_complete: bool
    _extracted_skills: list[dict[str, Any]]
