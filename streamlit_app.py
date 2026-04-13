"""Streamlit UI for the Adaptive Interview Gauntlet."""

from __future__ import annotations

import os
import uuid
from typing import Any

import streamlit as st
from langgraph.types import Command

from src.graph.workflow import workflow


def setup_environment() -> None:
    """Mirror the CLI environment defaults for Streamlit."""

    if not os.getenv("GAUNTLET_MODEL"):
        os.environ["GAUNTLET_MODEL"] = "google-gla:gemini-2.5-flash"

    # Always prefer an explicit GEMINI_API_KEY over whatever GOOGLE_API_KEY
    # was loaded when the process started — critical on Windows where env vars
    # set in a new PowerShell terminal don't propagate to a running process.
    if os.getenv("GEMINI_API_KEY"):
        os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]


def get_thread_config() -> dict[str, dict[str, str]]:
    """Create or reuse the thread config stored in Streamlit state."""

    if "thread_id" not in st.session_state:
        st.session_state.thread_id = str(uuid.uuid4())
    return {"configurable": {"thread_id": st.session_state.thread_id}}


def reset_session() -> None:
    """Reset the native LangGraph thread."""

    st.session_state.thread_id = str(uuid.uuid4())
    st.session_state.last_error = None
    st.session_state.building = False


def get_snapshot():
    """Return the current checkpointed graph state, if any."""

    try:
        return workflow.get_state(get_thread_config())
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def render_sidebar(snapshot) -> None:
    """Lean sidebar: API key status, reset, and a collapsed debug panel."""

    state = snapshot.values if snapshot is not None else {}
    with st.sidebar:
        # --- API Key ---
        current_key = os.getenv("GOOGLE_API_KEY", "")
        masked = f"{current_key[:8]}...{current_key[-4:]}" if len(current_key) > 12 else ("set" if current_key else "NOT SET")
        key_label = f"Key: `{masked}`" if current_key else "Key: **NOT SET**"
        with st.expander(key_label, expanded=not bool(current_key)):
            new_key = st.text_input(
                "Paste new API key",
                type="password",
                placeholder="AIza...",
                key="api_key_input",
            )
            if st.button("Apply", use_container_width=True) and new_key.strip():
                os.environ["GOOGLE_API_KEY"] = new_key.strip()
                os.environ["GEMINI_API_KEY"] = new_key.strip()
                st.rerun()

        st.divider()

        if st.button("Reset Session", use_container_width=True):
            reset_session()
            st.rerun()

        # --- Collapsed debug panel ---
        with st.expander("Debug", expanded=False):
            model = os.getenv("GAUNTLET_MODEL", "google-gla:gemini-2.5-flash")
            st.caption(f"Model: `{model}`")
            st.write(f"Phase: `{infer_phase(snapshot)}`")
            st.write(f"Company: {state.get('target_company', '—')}")
            st.write(f"Role: {state.get('target_role', '—')}")
            st.write(f"Skill: `{state.get('current_skill', '—')}`")
            st.write(f"Attempt: `{state.get('attempt_count', 0)}`  Hints: `{state.get('hints_used', 0)}`")
            st.write(f"Failures: `{state.get('consecutive_failures', 0)}`")
            mcp_result = state.get("mcp_result")
            st.write(f"MCP exit code: `{_extract_exit_code(mcp_result)}`")
            st.markdown("**Mastery**")
            st.json(state.get("mastery", {}))
            st.markdown("**MCP result**")
            st.json(_serialize_value(mcp_result) if mcp_result is not None else None)
            st.markdown("**Full state**")
            st.json(_serialize_state(state))


# ---------------------------------------------------------------------------
# Transcript
# ---------------------------------------------------------------------------

def render_transcript(snapshot) -> None:
    """Display the conversation transcript."""

    state = snapshot.values if snapshot is not None else {}
    st.subheader("Conversation")
    for message in state.get("session_transcript", []):
        role = message.get("role", "assistant")
        avatar = "assistant" if role == "assistant" else "user"
        with st.chat_message(avatar):
            st.markdown(message.get("content", ""))


# ---------------------------------------------------------------------------
# Boot Screen — Static Intake Form
# ---------------------------------------------------------------------------

def render_intake_form() -> None:
    """Render a clean, static intake form.  No graph execution until submit."""

    st.subheader("🧠 Build Your Personalized Learning Plan")
    st.write(
        "Paste any job description below. The system will analyze it, extract the specific "
        "technical skills the role requires, generate a personalized study guide with worked "
        "examples, and build practice questions tailored to that exact stack — not generic exercises."
    )

    if not os.getenv("GOOGLE_API_KEY"):
        st.warning(
            "⚠️ `GOOGLE_API_KEY` is not set. Set it before submitting.\n\n"
            "```powershell\n$env:GOOGLE_API_KEY='your-key-here'\n```"
        )

    with st.form("intake_form"):
        company = st.text_input(
            "Target Company",
            placeholder="e.g., ACME Corp",
        )
        role = st.text_input(
            "Position Title",
            placeholder="e.g., Senior Data Scientist",
        )
        jd_text = st.text_area(
            "Job Description",
            height=250,
            placeholder="Paste the full job description here...",
        )
        experience = st.text_area(
            "Your Experience / Study Needs",
            height=120,
            placeholder="e.g., I'm strong with Python and pandas but weak at SQL window functions. "
            "I've never done A/B testing in a production environment.",
        )

        submitted = st.form_submit_button("🚀 Build My Gauntlet", use_container_width=True)

    if submitted:
        if not jd_text or not jd_text.strip():
            st.error("Please paste a job description before starting.")
            return

        initial_state = {
            "provided_company": company.strip(),
            "provided_role": role.strip(),
            "raw_job_description": jd_text.strip(),
            "user_experience_needs": experience.strip(),
            "session_id": get_thread_config()["configurable"]["thread_id"],
            "session_transcript": [],
            "mastery_deltas": {},
            "question_history": [],
        }

        st.session_state.building = True
        _run_graph(initial_state)
        st.session_state.building = False
        st.rerun()


def render_building() -> None:
    """Show a clear building indicator while agents are running."""

    st.info(
        "⏳ **Building your personalized learning plan...**\n\n"
        "**Multi-agent pipeline running:**\n"
        "1. **Profile Builder** — parsing the job description and extracting technical skills\n"
        "2. **Proxy Generator** — creating executable test scenarios for each skill\n"
        "3. **Study Architect** — writing your personalized study guide with worked examples\n\n"
        "This takes 20-40 seconds. Hang tight."
    )


# ---------------------------------------------------------------------------
# Study Guide
# ---------------------------------------------------------------------------

def render_study_guide(snapshot) -> None:
    """Render the pre-practice study guide step."""

    state = snapshot.values if snapshot is not None else {}
    st.subheader("📚 Your Personalized Study Guide")

    # Show extracted skills as pills
    skills = state.get("job_requirements", [])
    proxies = state.get("skill_proxies", [])
    if skills:
        proxy_map = {}
        for p in proxies:
            ptype = p.proxy_type if hasattr(p, "proxy_type") else p.get("proxy_type", "")
            pname = p.original_skill if hasattr(p, "original_skill") else p.get("original_skill", "")
            proxy_map[pname] = ptype
        pills = []
        for s in skills:
            ptype = proxy_map.get(s, "")
            badge = " `python`" if "python" in ptype else (" `sql`" if "sql" in ptype else " `conceptual`")
            pills.append(f"`{s}`{badge}")
        st.markdown("**Skills extracted from your JD:** " + " · ".join(pills))
        st.caption(
            "Python/SQL skills run through the deterministic MCP sandbox. "
            "Conceptual skills are evaluated by the LLM Judge."
        )
        st.divider()

    st.markdown(state.get("study_guide", ""))

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Start Practice", type="primary", use_container_width=True):
            _resume_graph({"action": "start"})
            st.rerun()
    with col2:
        if st.button("Skip Study Guide", use_container_width=True):
            _resume_graph({"action": "skip"})
            st.rerun()


# ---------------------------------------------------------------------------
# Question Panel
# ---------------------------------------------------------------------------

def render_question_panel(snapshot) -> None:
    """Clean question view: question, editor, three action buttons."""

    state = snapshot.values if snapshot is not None else {}
    question = state.get("current_question")
    if question is None:
        st.warning("No active question is loaded.")
        return

    proxy = state.get("current_proxy")
    proxy_type = ""
    if proxy is not None:
        proxy_type = proxy.proxy_type if hasattr(proxy, "proxy_type") else proxy.get("proxy_type", "")
    is_conceptual = proxy_type == "conceptual"

    # Show feedback from the previous question if it exists and is for a different skill
    latest_score = state.get("latest_question_score")
    current_skill = state.get("current_skill", "")
    if latest_score is not None:
        prev_skill = latest_score.skill if hasattr(latest_score, "skill") else (latest_score.get("skill") if isinstance(latest_score, dict) else "")
        if prev_skill and prev_skill != current_skill:
            narrative = latest_score.narrative if hasattr(latest_score, "narrative") else (latest_score.get("narrative") if isinstance(latest_score, dict) else "")
            score_val = latest_score.score if hasattr(latest_score, "score") else (latest_score.get("score") if isinstance(latest_score, dict) else 0.0)
            if narrative:
                with st.container(border=True):
                    st.caption(f"Feedback on **{prev_skill}** — score {score_val:.0%}")
                    st.markdown(narrative)

    # Skill + attempt context in a single quiet line
    attempt = int(state.get("attempt_count", 0))
    hints = int(state.get("hints_used", 0))
    context_parts = []
    if current_skill:
        context_parts.append(f"**{current_skill}**")
    if is_conceptual:
        context_parts.append("conceptual — LLM evaluated")
    if attempt:
        context_parts.append(f"attempt {attempt + 1}/3")
    if hints:
        context_parts.append(f"{hints} hint{'s' if hints != 1 else ''} used")
    if context_parts:
        st.caption(" · ".join(context_parts))

    # The question itself — prominent
    question_text = question.text if hasattr(question, "text") else question.get("text", "")
    st.markdown(question_text)

    # Sandbox execution results (executable skills only) — shown after any attempt
    mcp_result = state.get("mcp_result")
    if mcp_result is not None:
        _render_sandbox_results(mcp_result)

    st.divider()

    if is_conceptual:
        placeholder = (
            "Type your answer here.\n\n"
            "Include code snippets using markdown fences (```python / ```js / etc.) if relevant.\n"
            "Cover all the numbered points listed in the question above."
        )
    elif proxy_type == "sql_duckdb":
        placeholder = "-- Write your SQL query here\nSELECT ..."
    else:
        placeholder = "# Write your Python solution here\nimport pandas as pd\n"

    submission = st.text_area(
        "Your answer",
        value=state.get("user_submission") or "",
        height=280,
        placeholder=placeholder,
        label_visibility="collapsed",
    )

    col1, col2, col3 = st.columns([3, 1, 1])
    with col1:
        submit_label = "Submit Answer" if is_conceptual else "Run & Submit"
        if st.button(submit_label, type="primary", use_container_width=True):
            _resume_graph({"event": "submission", "submission": submission})
            st.rerun()
    with col2:
        if st.button("Hint", use_container_width=True):
            _resume_graph({"event": "hint"})
            st.rerun()
    with col3:
        if st.button("Reteach", use_container_width=True):
            _resume_graph({"event": "timeout"})
            st.rerun()


# ---------------------------------------------------------------------------
# Completion
# ---------------------------------------------------------------------------

def render_completion(snapshot) -> None:
    """Render the end-of-session summary."""

    state = snapshot.values if snapshot is not None else {}
    st.success("Learning session complete")
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Session Score", f"{state.get('session_score', 0.0):.0%}")
    with col2:
        mastery = state.get("mastery", {})
        if mastery:
            avg = sum(mastery.values()) / len(mastery)
            st.metric("Avg Mastery", f"{avg:.0%}")
    st.markdown("### What the Judge Said")
    st.markdown(state.get("judge_narrative", "No narrative provided."))
    if state.get("top_priority_next_session"):
        st.info(f"**Study this next session:** {state['top_priority_next_session']}")
    mastery = state.get("mastery", {})
    if mastery:
        st.markdown("### Mastery After This Session")
        for skill, score in mastery.items():
            st.progress(float(score), text=f"{skill}: {score:.0%}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the Streamlit application."""

    setup_environment()
    st.set_page_config(page_title="Adaptive Learning Gauntlet", page_icon="🧠", layout="wide")
    st.title("🧠 Adaptive Learning Gauntlet")
    st.caption("Paste any job description → LLM extracts skills → personalized study guide → live practice with deterministic code execution → mastery tracking.")

    snapshot = get_snapshot()
    render_sidebar(snapshot)

    phase = infer_phase(snapshot)
    render_error_banner()

    if phase == "booting":
        render_intake_form()
        return
    if phase == "building":
        render_building()
        return
    if phase == "study_guide":
        render_study_guide(snapshot)
        return
    if phase == "question":
        render_question_panel(snapshot)
        return
    if phase == "complete":
        render_transcript(snapshot)
        render_completion(snapshot)
        return

    st.info("Session is initializing...")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize_state(state: dict[str, Any]) -> dict[str, Any]:
    """Convert Pydantic state values into JSON-friendly objects for debugging."""
    return {key: _serialize_value(value) for key, value in state.items()}


def _serialize_value(value: Any):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_serialize_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize_value(item) for key, item in value.items()}
    return value


def render_error_banner() -> None:
    """Show a contextual error with a Try Again button when graph execution fails.

    Passes None to _run_graph so LangGraph resumes from the last successful
    checkpoint rather than restarting the session from scratch.
    """
    error_msg = st.session_state.get("last_error")
    if not error_msg:
        return

    msg_lower = error_msg.lower()
    is_capacity = any(k in msg_lower for k in ("503", "overloaded", "unavailable", "resource_exhausted"))
    is_auth = any(k in msg_lower for k in ("400", "api_key_invalid", "expired", "api key"))

    if is_capacity:
        headline = "Gemini is temporarily overloaded — all fallback models were busy."
        advice = "Click **Try Again**. The system will retry with the next available model."
    elif is_auth:
        headline = "API key error."
        advice = "Paste a fresh key in the **API Key** widget in the sidebar, then click **Try Again**."
    else:
        headline = "Something went wrong during the last step."
        advice = "Click **Try Again** to retry from where you left off."

    with st.container(border=True):
        st.warning(f"**{headline}** {advice}")
        col_btn, col_detail = st.columns([1, 3])
        with col_btn:
            if st.button("Try Again", type="primary", use_container_width=True):
                st.session_state.last_error = None
                # Resume from the last successful LangGraph checkpoint —
                # no need to restart the session or replay the intake form.
                _run_graph(None)
                st.rerun()
        with col_detail:
            with st.expander("Error details"):
                st.code(error_msg, language="text")


def _run_graph(input_value: Any):
    config = get_thread_config()
    try:
        for _ in workflow.stream(input_value, config):
            pass
        st.session_state.last_error = None
    except Exception as exc:
        st.session_state.last_error = str(exc)
    return get_snapshot()


def _resume_graph(resume_value: Any):
    return _run_graph(Command(resume=resume_value))


def infer_phase(snapshot) -> str:
    """Determine the current UI phase from graph state."""

    # If Streamlit is in the middle of a build, show building state
    if st.session_state.get("building"):
        return "building"

    # No snapshot = no graph execution yet = show the intake form
    if snapshot is None:
        return "booting"

    state = snapshot.values

    # Empty state (graph hasn't been started)
    if not state:
        return "booting"

    if state.get("session_complete"):
        return "complete"

    if snapshot.interrupts:
        interrupt_value = snapshot.interrupts[0].value
        if isinstance(interrupt_value, dict):
            kind = interrupt_value.get("kind")
            if kind == "present_study_guide":
                return "study_guide"
            if kind == "receive_submission":
                return "question"

    # Study guide built, no question yet → waiting at study guide
    if state.get("study_guide") and not state.get("current_question"):
        return "study_guide"

    # Question is loaded and we're mid-interview (interrupt consumed, e.g. after a node failure
    # or while waiting for MCP/judge to complete) — stay on question page, not the spinner
    if state.get("current_question"):
        return "question"

    return "building"


_TEST_LABELS = {
    "happy_path":    "Happy path",
    "null":          "Null / missing value handling",
    "edge":          "Edge case (empty / single row)",
    "duplicate":     "Duplicate / tie handling",
    "performance":   "Grain / shape correctness",
}

def _render_sandbox_results(mcp_result: Any) -> None:
    """Show a per-test pass/fail grid so the MCP sandbox is visibly useful."""
    exit_code = _extract_exit_code(mcp_result)
    passed = getattr(mcp_result, "tests_passed", 0) if not isinstance(mcp_result, dict) else mcp_result.get("tests_passed", 0)
    total  = getattr(mcp_result, "tests_total",  0) if not isinstance(mcp_result, dict) else mcp_result.get("tests_total",  0)
    elapsed = getattr(mcp_result, "execution_time_ms", 0.0) if not isinstance(mcp_result, dict) else mcp_result.get("execution_time_ms", 0.0)
    results = getattr(mcp_result, "results", []) if not isinstance(mcp_result, dict) else mcp_result.get("results", [])
    stderr  = getattr(mcp_result, "stderr", "")  if not isinstance(mcp_result, dict) else mcp_result.get("stderr", "")

    all_passed  = exit_code == 0
    header_icon = "✅" if all_passed else "❌"
    with st.container(border=True):
        st.markdown(f"**{header_icon} Sandbox execution — {passed}/{total} tests passed** &nbsp; `{elapsed:.0f} ms`")

        if results:
            for r in results:
                test_id  = r.get("test_id", "test")
                ok       = r.get("passed", False)
                label    = _TEST_LABELS.get(test_id, test_id.replace("_", " ").title())
                icon     = "✅" if ok else "❌"
                st.markdown(f"&nbsp;&nbsp;{icon} {label}")
                if not ok:
                    tb = r.get("traceback") or ""
                    if tb:
                        with st.expander("Error detail"):
                            # Trim noisy internal frames — show only the last meaningful line
                            last_line = [l.strip() for l in tb.splitlines() if l.strip()]
                            st.code("\n".join(last_line[-6:]), language="text")
        elif stderr:
            # Fallback: no per-test data, show raw stderr
            with st.expander("Error detail"):
                st.code(stderr, language="text")


def _extract_exit_code(mcp_result: Any) -> int | None:
    if mcp_result is None:
        return None
    if hasattr(mcp_result, "exit_code"):
        return mcp_result.exit_code
    if isinstance(mcp_result, dict):
        return mcp_result.get("exit_code")
    return None


def _extract_mcp_display(mcp_result: Any) -> tuple[int, int, str]:
    if hasattr(mcp_result, "tests_passed"):
        return mcp_result.tests_passed, mcp_result.tests_total, mcp_result.stderr
    return (
        int(mcp_result.get("tests_passed", 0)),
        int(mcp_result.get("tests_total", 0)),
        str(mcp_result.get("stderr", "")),
    )


if __name__ == "__main__":
    main()
