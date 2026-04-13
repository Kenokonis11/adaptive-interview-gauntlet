"""LangGraph nodes wired to config, agents, MCP tools, and mastery storage."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import yaml
from langgraph.types import interrupt

from src.agents.hiring_manager import run_manager
from src.agents.judge import run_question_judge, run_session_judge
from src.agents.qa_engineer import run_qa
from src.graph.state import InterviewState, MCPResult, Question, SkillProxy
from src.mcp.executor import execute_python_with_tests
from src.mcp.sql_executor import execute_sql_with_tests
from src.memory.mastery import load_mastery, load_mastery_full_data, write_mastery
from src.memory.vector_store import get_previous_questions, log_question


DEFAULT_JOB_PATH = "configs/acme_data_scientist.yaml"
DEFAULT_MASTERY_PATH = "data/user_mastery.json"


def load_job_config(state: InterviewState) -> dict[str, Any]:
    """Load YAML config plus the persisted mastery profile."""

    config_path = state.get("job_yaml_path", DEFAULT_JOB_PATH)
    config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}

    job_requirements = list(config.get("core_requirements", []))
    raw_proxies = config.get("skill_proxies", [])
    normalized_proxies = _normalize_skill_proxies(raw_proxies)
    mastery_path = state.get("mastery_file_path", DEFAULT_MASTERY_PATH)
    mastery_full_data = load_mastery_full_data(mastery_path, job_requirements)
    mastery = load_mastery(mastery_path)

    return {
        "job_yaml_path": config_path,
        "target_company": config.get("target_company", ""),
        "target_role": config.get("role", ""),
        "session_id": state.get("session_id") or str(uuid.uuid4()),
        "mastery": mastery,
        "job_requirements": job_requirements,
        "study_guide": "",
        "skill_proxies": normalized_proxies,
        "current_question": None,
        "current_skill": "",
        "previous_questions": [],
        "user_submission": None,
        "submission_event": None,
        "attempt_count": 0,
        "consecutive_failures": 0,
        "mcp_result": None,
        "session_transcript": list(state.get("session_transcript", [])),
        "mastery_deltas": dict(state.get("mastery_deltas", {})),
        "session_score": 0.0,
        "judge_narrative": "",
        "mastery_alpha": float(config.get("mastery_alpha", 0.3)),
        "mastery_file_path": mastery_path,
        "mastery_full_data": mastery_full_data,
        "prioritized_skills": list(state.get("prioritized_skills", [])),
        "hints_used": 0,
        "pending_tests": None,
        "latest_question_score": None,
        "guide_action": None,
        "current_proxy": None,
        "top_priority_next_session": None,
        "question_history": list(state.get("question_history", [])),
        "reuse_current_question": False,
        "error_message": None,
        "session_complete": False,
    }


def build_profile(state: InterviewState) -> dict[str, Any]:
    """Run the Profile Builder agent to extract structured skills from the JD.

    Uses provided_company and provided_role from the intake form as strong
    hints, falling back to LLM-extracted values if they're empty.
    """

    from src.agents.profile_builder import run_profile_builder

    raw_jd = state.get("raw_job_description", "")
    profile = run_profile_builder(raw_jd)

    extracted_skills = profile.core_skills
    job_requirements = [skill.skill_name for skill in extracted_skills]

    # Prefer user-provided company/role; fall back to LLM-extracted values
    company = state.get("provided_company", "").strip() or profile.company_name or "Unknown Company"
    role = state.get("provided_role", "").strip() or profile.job_title or "Unknown Role"

    mastery_path = state.get("mastery_file_path", DEFAULT_MASTERY_PATH)
    mastery_full_data = load_mastery_full_data(mastery_path, job_requirements)
    mastery = load_mastery(mastery_path)

    transcript = list(state.get("session_transcript", []))
    transcript.append(
        {
            "role": "assistant",
            "content": f"Analyzed job posting for **{role}** at **{company}**. "
            f"Extracted {len(extracted_skills)} skills: {', '.join(job_requirements)}.",
        }
    )

    return {
        "target_company": company,
        "target_role": role,
        "job_requirements": job_requirements,
        "session_id": state.get("session_id") or str(uuid.uuid4()),
        "mastery": mastery,
        "mastery_file_path": mastery_path,
        "mastery_full_data": mastery_full_data,
        "mastery_alpha": 0.3,
        "session_transcript": transcript,
        "mastery_deltas": dict(state.get("mastery_deltas", {})),
        "question_history": list(state.get("question_history", [])),
        # Store extracted skills in state for proxy generation
        "_extracted_skills": [skill.model_dump() for skill in extracted_skills],
        # Initialize loop state
        "current_question": None,
        "current_skill": "",
        "previous_questions": [],
        "user_submission": None,
        "submission_event": None,
        "attempt_count": 0,
        "consecutive_failures": 0,
        "mcp_result": None,
        "study_guide": "",
        "session_score": 0.0,
        "judge_narrative": "",
        "hints_used": 0,
        "pending_tests": None,
        "latest_question_score": None,
        "guide_action": None,
        "current_proxy": None,
        "top_priority_next_session": None,
        "reuse_current_question": False,
        "error_message": None,
        "session_complete": False,
    }


def generate_proxies(state: InterviewState) -> dict[str, Any]:
    """Run the Proxy Generator agent to create validated test proxies."""

    from src.agents.proxy_generator import run_proxy_generator
    from src.agents.schemas import ExtractedSkill

    extracted_skills_raw = state.get("_extracted_skills", [])
    skills = [ExtractedSkill.model_validate(s) for s in extracted_skills_raw]

    proxies = run_proxy_generator(skills)
    job_requirements = [p.original_skill for p in proxies]

    return {
        "skill_proxies": proxies,
        "prioritized_skills": job_requirements,
    }


def run_study_architect(state: InterviewState) -> dict[str, Any]:
    """Generate the personalized study guide via LLM, ordered by skill priority."""

    from src.agents.study_architect import run_architect

    skill_proxies = state.get("skill_proxies", [])
    result = run_architect(dict(state))

    # Reorder proxies to match the LLM's priority ordering
    proxies_by_skill = {proxy.original_skill: proxy for proxy in skill_proxies}
    ordered_proxies = [proxies_by_skill[s] for s in result.prioritized_skills if s in proxies_by_skill]
    # Include any proxies not mentioned in prioritized_skills at the end
    included = set(result.prioritized_skills)
    ordered_proxies += [p for p in skill_proxies if p.original_skill not in included]

    return {
        "study_guide": result.study_guide,
        "prioritized_skills": result.prioritized_skills or state.get("job_requirements", []),
        "skill_proxies": ordered_proxies or skill_proxies,
    }


def present_study_guide(state: InterviewState) -> dict[str, Any]:
    """Pause for acknowledgement using LangGraph's native interrupt."""

    guide = state.get("study_guide", "")
    action = interrupt(
        {
            "kind": "present_study_guide",
            "study_guide": guide,
            "options": ["start", "skip"],
        }
    )
    action_value = _extract_action_value(action, default="start")
    transcript = list(state.get("session_transcript", []))
    if guide and (not transcript or transcript[-1].get("content") != guide):
        transcript.append({"role": "assistant", "content": guide})
    transcript.append({"role": "user", "content": action_value})
    return {"guide_action": action_value, "session_transcript": transcript}


def ask_question(state: InterviewState) -> dict[str, Any]:
    """Ask the next interview question, or replay a reteach follow-up."""

    transcript = list(state.get("session_transcript", []))
    question_history = list(state.get("question_history", []))

    if state.get("reuse_current_question") and state.get("current_question") is not None:
        current_question = state["current_question"]
        response_text = current_question.text
        transcript.append({"role": "assistant", "content": response_text})
        return {
            "attempt_count": 0,
            "user_submission": None,
            "submission_event": None,
            "mcp_result": None,
            "pending_tests": None,
            "reuse_current_question": False,
            "session_transcript": transcript,
        }

    next_skill = _next_skill(state)
    if next_skill is None:
        return {"session_complete": True}

    proxy = _proxy_for_skill(state, next_skill)
    previous_questions = get_previous_questions(next_skill)
    manager_state = dict(state)
    manager_state.update(
        {
            "current_skill": next_skill,
            "attempt_count": 0,
            "mcp_result": None,
            "previous_questions": previous_questions,
        }
    )
    response_text = run_manager(manager_state)
    current_question = Question(
        text=response_text,
        skill=next_skill,
        difficulty=proxy.difficulty_default if proxy is not None else "standard",
        expected_concepts=_expected_concepts(next_skill, proxy),
    )
    question_history.append(current_question)
    transcript.append({"role": "assistant", "content": response_text})

    return {
        "current_skill": next_skill,
        "current_proxy": proxy,
        "current_question": current_question,
        "previous_questions": previous_questions,
        "attempt_count": 0,
        "consecutive_failures": 0,
        "user_submission": None,
        "submission_event": None,
        "mcp_result": None,
        "pending_tests": None,
        "hints_used": 0,
        "question_history": question_history,
        "session_transcript": transcript,
        "reuse_current_question": False,
    }


def receive_submission(state: InterviewState) -> dict[str, Any]:
    """Pause for a submission/hint/timeout using LangGraph's native interrupt."""

    question = state.get("current_question")
    response = interrupt(
        {
            "kind": "receive_submission",
            "question_text": question.text if question is not None else "",
            "attempt_count": int(state.get("attempt_count", 0)),
            "options": ["submit", "hint", "timeout"],
        }
    )
    event, raw_value = _extract_submission_payload(response)
    transcript = list(state.get("session_transcript", []))
    payload = raw_value if raw_value else str(event or "")
    if payload and (not transcript or transcript[-1].get("content") != payload):
        transcript.append({"role": "user", "content": payload})

    if event == "hint":
        return {"submission_event": "hint", "user_submission": None, "session_transcript": transcript}
    if event == "timeout":
        return {"submission_event": "timeout", "user_submission": None, "session_transcript": transcript}
    return {"submission_event": "submission", "user_submission": raw_value, "session_transcript": transcript}


def deliver_hint(state: InterviewState) -> dict[str, Any]:
    """Ask the Hiring Manager for a hint and charge one hint use."""

    response_text = run_manager(dict(state))
    transcript = list(state.get("session_transcript", []))
    transcript.append({"role": "assistant", "content": response_text})
    return {
        "hints_used": int(state.get("hints_used", 0)) + 1,
        "session_transcript": transcript,
    }


def run_qa_engineer(state: InterviewState) -> dict[str, Any]:
    """Generate hidden test cases for the current question, or reuse cached tests on retry."""

    existing = state.get("pending_tests")
    if existing is not None:
        return {"pending_tests": existing}

    qa_result = run_qa(dict(state))
    return {"pending_tests": qa_result}


def execute_via_mcp(state: InterviewState) -> dict[str, Any]:
    """Run the candidate submission through the deterministic sandbox directly.

    Bypasses the MCP subprocess client to avoid anyio.run() conflicts
    with Streamlit's event loop. Calls executor functions in-process.
    # TODO: re-add subprocess isolation via MCP client once flow is validated
    """

    pending_tests = state.get("pending_tests")
    if pending_tests is None:
        raise ValueError("QA test cases must exist before execution.")

    user_submission = state.get("user_submission") or ""
    proxy = state.get("current_proxy") or _proxy_for_skill(state, state.get("current_skill", ""))

    if pending_tests.tool_name == "execute_sql_with_tests":
        raw_result = execute_sql_with_tests(
            user_query=user_submission,
            schema_setup=pending_tests.schema_setup or (proxy.test_dataset if proxy is not None else ""),
            test_cases=[test_case.model_dump() for test_case in pending_tests.test_cases],
            timeout_seconds=10,
        )
    else:
        raw_result = execute_python_with_tests(
            user_code=user_submission,
            test_cases=[test_case.model_dump() for test_case in pending_tests.test_cases],
            timeout_seconds=10,
        )

    mcp_result = MCPResult.model_validate(raw_result)
    return {
        "mcp_result": mcp_result,
        "attempt_count": int(state.get("attempt_count", 0)) + 1,
    }


def deliver_feedback(state: InterviewState) -> dict[str, Any]:
    """Return Hiring Manager feedback after a failed attempt."""

    response_text = run_manager(dict(state))
    transcript = list(state.get("session_transcript", []))
    transcript.append({"role": "assistant", "content": response_text})
    return {"session_transcript": transcript}


def reteach(state: InterviewState) -> dict[str, Any]:
    """Switch into tutor mode and preload a simpler follow-up question."""

    response_text = run_manager(dict(state))
    transcript = list(state.get("session_transcript", []))
    transcript.append({"role": "assistant", "content": response_text})
    new_question_text = _extract_new_question(response_text)
    proxy = state.get("current_proxy") or _proxy_for_skill(state, state.get("current_skill", ""))

    current_question = Question(
        text=new_question_text,
        skill=state.get("current_skill", ""),
        difficulty="warm_up",
        expected_concepts=_expected_concepts(state.get("current_skill", ""), proxy),
    )
    question_history = list(state.get("question_history", []))
    question_history.append(current_question)

    return {
        "current_question": current_question,
        "attempt_count": 0,
        "consecutive_failures": int(state.get("consecutive_failures", 0)) + 1,
        "pending_tests": None,
        "mcp_result": None,
        "user_submission": None,
        "reuse_current_question": True,
        "question_history": question_history,
        "session_transcript": transcript,
    }


def run_judge(state: InterviewState) -> dict[str, Any]:
    """Score the current question and accumulate mastery deltas."""

    score = run_question_judge(dict(state))
    mastery_deltas = dict(state.get("mastery_deltas", {}))
    mastery_deltas[score.skill] = score.score
    current_question = state.get("current_question")
    if current_question is not None:
        log_question(score.skill, current_question.text)
    transcript = list(state.get("session_transcript", []))
    transcript.append({"role": "assistant", "content": score.narrative})
    return {
        "latest_question_score": score,
        "mastery_deltas": mastery_deltas,
        "session_transcript": transcript,
        "current_question": None,
        "attempt_count": 0,
        "hints_used": 0,
        "submission_event": None,
        "pending_tests": None,
        "mcp_result": None,
        "user_submission": None,
        "reuse_current_question": False,
    }


def end_session(state: InterviewState) -> dict[str, Any]:
    """Produce the end-of-session report."""

    report = run_session_judge(dict(state))
    transcript = list(state.get("session_transcript", []))
    transcript.append({"role": "assistant", "content": report.narrative})
    return {
        "session_score": report.session_score,
        "judge_narrative": report.narrative,
        "top_priority_next_session": report.top_priority_next_session,
        "session_transcript": transcript,
        "session_complete": True,
    }


def update_mastery(state: InterviewState) -> dict[str, Any]:
    """Persist mastery updates exactly once at session end."""

    write_mastery(
        path=state.get("mastery_file_path", DEFAULT_MASTERY_PATH),
        deltas=state.get("mastery_deltas", {}),
        full_data=state.get("mastery_full_data", {}),
        alpha=float(state.get("mastery_alpha", 0.3)),
    )
    updated_mastery = load_mastery(state.get("mastery_file_path", DEFAULT_MASTERY_PATH))
    return {"mastery": updated_mastery, "session_complete": True}


def _normalize_skill_proxies(raw_proxies: Any) -> list[SkillProxy]:
    if isinstance(raw_proxies, list):
        return [SkillProxy.model_validate(proxy) for proxy in raw_proxies]

    normalized: list[SkillProxy] = []
    if isinstance(raw_proxies, dict):
        for skill_name, proxy in raw_proxies.items():
            if isinstance(proxy, dict):
                normalized.append(
                    SkillProxy(
                        original_skill=proxy.get("original_skill", skill_name),
                        proxy_type=proxy.get("proxy_type", "python_general"),
                        proxy_context=proxy.get("proxy_context", ""),
                        test_dataset=proxy.get("test_dataset", ""),
                        difficulty_default=proxy.get("difficulty_default", "standard"),
                    )
                )
    return normalized


def _next_skill(state: InterviewState) -> str | None:
    completed = set(state.get("mastery_deltas", {}).keys())
    prioritized = state.get("prioritized_skills") or [proxy.original_skill for proxy in state.get("skill_proxies", [])]
    for skill in prioritized:
        if skill not in completed:
            return skill
    return None


def _proxy_for_skill(state: InterviewState, skill: str) -> SkillProxy | None:
    for proxy in state.get("skill_proxies", []):
        if proxy.original_skill == skill:
            return proxy
    return None


def _expected_concepts(skill: str, proxy: SkillProxy | None) -> list[str]:
    concepts = [skill] if skill else []
    if proxy is not None:
        concepts.append(proxy.proxy_type)
        if proxy.proxy_context:
            concepts.append(proxy.proxy_context[:120])
    return concepts


def _extract_new_question(response_text: str) -> str:
    marker = "[NEW QUESTION]"
    if marker in response_text:
        return response_text.split(marker, maxsplit=1)[1].strip()
    return response_text.strip()


def _extract_action_value(value: Any, default: str) -> str:
    if isinstance(value, dict):
        raw_value = value.get("action", default)
    else:
        raw_value = value
    return str(raw_value or default).strip().lower()


def _extract_submission_payload(value: Any) -> tuple[str, str]:
    if isinstance(value, dict):
        event = str(value.get("event", "submission")).strip().lower() or "submission"
        submission = str(value.get("submission", "") or "").strip()
        return event, submission

    lowered = str(value or "").strip()
    normalized = lowered.lower()
    if normalized in {"hint", "timeout"}:
        return normalized, ""
    return "submission", lowered
