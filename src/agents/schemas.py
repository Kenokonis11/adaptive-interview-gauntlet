"""Shared Pydantic schemas for agent outputs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ExtractedSkill(BaseModel):
    """A single skill extracted from the job description."""

    model_config = ConfigDict(extra="forbid")

    skill_name: str = Field(description="Specific technical skill (e.g., 'Pandas Data Wrangling').")
    category: Literal["executable_python", "executable_sql", "conceptual"] = Field(
        description="Whether this skill can be tested via Python code, SQL, or verbal Q&A."
    )
    context_from_jd: str = Field(description="How the job description specifically frames this skill.")


class DynamicJobProfile(BaseModel):
    """Structured extraction output from the Profile Builder agent."""

    model_config = ConfigDict(extra="forbid")

    company_name: str
    job_title: str
    core_skills: list[ExtractedSkill] = Field(min_length=1, max_length=8)


class StudyGuideResult(BaseModel):
    """Structured output from the Study Architect."""

    model_config = ConfigDict(extra="forbid")

    study_guide: str
    prioritized_skills: list[str] = Field(default_factory=list)


class PythonTestCase(BaseModel):
    """Hidden Python test case for the MCP executor."""

    model_config = ConfigDict(extra="forbid")

    test_id: str
    setup_code: str
    assertion_code: str


class SQLTestCase(BaseModel):
    """Hidden SQL validation case for the DuckDB executor."""

    model_config = ConfigDict(extra="forbid")

    test_id: str
    validation_query: str
    description: str


class QATestCases(BaseModel):
    """Structured QA output that mirrors the downstream MCP tool inputs."""

    model_config = ConfigDict(extra="ignore")

    tool_name: Literal["execute_python_with_tests", "execute_sql_with_tests"]
    schema_setup: str | None = None
    user_code: str | None = None
    user_query: str | None = None
    test_cases: list[PythonTestCase | SQLTestCase]

    @model_validator(mode="after")
    def validate_shape(self) -> "QATestCases":
        if len(self.test_cases) != 5:
            raise ValueError("QA Engineer must return exactly 5 test cases.")

        if self.tool_name == "execute_python_with_tests":
            if self.schema_setup not in (None, ""):
                raise ValueError("schema_setup must be omitted for Python test cases.")
            if not all(isinstance(test_case, PythonTestCase) for test_case in self.test_cases):
                raise ValueError("Python QA output must contain only PythonTestCase items.")
            return self

        if not self.schema_setup:
            raise ValueError("schema_setup is required for SQL test cases.")
        if not all(isinstance(test_case, SQLTestCase) for test_case in self.test_cases):
            raise ValueError("SQL QA output must contain only SQLTestCase items.")
        return self


class QuestionScore(BaseModel):
    """Per-question scoring produced by the Judge."""

    model_config = ConfigDict(extra="forbid")

    skill: str
    score: float
    prior_mastery: float
    delta: float
    narrative: str


class SessionReport(BaseModel):
    """End-of-session synthesis produced by the Judge."""

    model_config = ConfigDict(extra="forbid")

    session_score: float
    narrative: str
    top_priority_next_session: str
