"""Profile Builder agent — extracts structured skills from a raw job description."""

from __future__ import annotations

from src.agents._runtime import run_structured
from src.agents.schemas import DynamicJobProfile


PROFILE_BUILDER_PROMPT = """You are a Profile Builder for a technical learning platform.

You will receive the raw text of a job description. Your job is to extract a structured profile.

Rules:
1. Extract 3-6 concrete, testable technical skills from the job description.
2. Classify each skill into one of three categories:
   - "executable_python": Skills testable via Python code (data wrangling, algorithms, ML pipelines,
     pandas, numpy, scikit-learn, feature engineering, etc.)
   - "executable_sql": Skills testable via SQL queries (window functions, joins, aggregations, CTEs,
     subqueries, etc.)
   - "conceptual": Everything else — statistical theory, A/B testing design, system design,
     JavaScript/TypeScript, React, cloud infrastructure, business logic, any non-Python/SQL language.
3. For each skill, quote or paraphrase the specific language from the JD that describes the requirement.
4. Extract the company name and job title from the JD. If not found, use reasonable defaults.
5. Do NOT invent skills not present in the JD.
6. Prefer executable skills over conceptual ones when the skill could be demonstrated either way in Python or SQL.

Return valid JSON matching the DynamicJobProfile schema.
"""


def run_profile_builder(raw_jd: str) -> DynamicJobProfile:
    """Extract a structured job profile from raw job description text."""

    return run_structured(
        PROFILE_BUILDER_PROMPT,
        f"Extract the profile from this job description:\n\n{raw_jd}",
        DynamicJobProfile,
    )
