"""Study Architect agent wrappers."""

from __future__ import annotations

from src.agents._runtime import dump_for_prompt, run_structured, state_value
from src.agents.schemas import StudyGuideResult


STUDY_ARCHITECT_SYSTEM = """You are a Study Architect for a personalized technical learning platform.

Your job is to produce a rich, personalized pre-practice study guide based on the candidate's
job description, current mastery, and self-reported experience.

== FORMAT REQUIREMENTS ==

Return valid JSON with two fields:
  "study_guide": a markdown string (described below)
  "prioritized_skills": list of skill names in the order they should be practiced

== STUDY GUIDE CONTENT REQUIREMENTS ==

The study guide must contain, for EACH skill:

1. **What this skill is and why it matters** for this specific role (2-3 sentences).
   Reference the job description context where relevant.

2. **What will be tested** — a numbered list of the specific things the practice question checks.
   Be concrete: name functions, methods, column names, SQL clauses.

3. **A worked example** — complete, runnable code (Python or SQL) that demonstrates the core pattern.
   For conceptual skills, a clear written example of the correct reasoning.

4. **A mastery note** — flag mastery=0.0 as "⚠️ Not yet demonstrated — starting with a warm-up".
   Acknowledge the candidate's self-reported strengths and weaknesses by name.

Rules:
- Prioritize skills the candidate said they are weak at, regardless of mastery score.
- Do NOT invent skills not present in the job requirements.
- Produce code examples for every executable skill — this is a coding platform, not a lecture.
- Keep each skill section under 300 words.
"""


def run_architect(state_dict: dict) -> StudyGuideResult:
    """Run the Study Architect with strict structured parsing."""

    target_company = state_value(state_dict, "target_company", default="")
    target_role = state_value(state_dict, "target_role", "role", default="")
    job_requirements = state_value(state_dict, "job_requirements", "core_requirements", default=[])
    mastery = state_value(state_dict, "mastery", "mastery_snapshot", default={})
    user_experience_needs = state_value(state_dict, "user_experience_needs", default="Not provided.")

    context = f"""Target company: {target_company}
Target role: {target_role}
Skills extracted from job description: {dump_for_prompt(job_requirements)}
Candidate mastery profile (0.0=none, 1.0=expert): {dump_for_prompt(mastery)}
Candidate self-reported experience and weak areas: {user_experience_needs or "Not provided."}

Produce the personalized study guide now."""

    return run_structured(STUDY_ARCHITECT_SYSTEM, context, StudyGuideResult)
