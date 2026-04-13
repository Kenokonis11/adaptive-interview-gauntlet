"""LangGraph workflow compilation for the adaptive interview graph."""

from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from src.graph.edges import evaluate_result, route_after_judge, route_after_question, route_human_input
from src.graph.nodes import (
    ask_question,
    build_profile,
    deliver_feedback,
    deliver_hint,
    end_session,
    execute_via_mcp,
    generate_proxies,
    load_job_config,
    present_study_guide,
    receive_submission,
    reteach,
    run_judge,
    run_qa_engineer,
    run_study_architect,
    update_mastery,
)
from src.graph.state import InterviewState


checkpointer = MemorySaver()


def build_workflow():
    """Create and compile the interview workflow graph.

    New entry flow:
        receive_job_description (INTERRUPT) → build_profile → generate_proxies
        → run_study_architect → present_study_guide (INTERRUPT)
        → [existing evaluation loop]
    """

    graph = StateGraph(InterviewState)

    # Phase 1: Dynamic Ingestion (no interrupt — Streamlit injects state directly)
    graph.add_node("build_profile", build_profile)
    graph.add_node("generate_proxies", generate_proxies)

    # Phase 2: Study Guide
    graph.add_node("run_study_architect", run_study_architect)
    graph.add_node("present_study_guide", present_study_guide)

    # Phase 3: Interview Loop
    graph.add_node("ask_question", ask_question)
    graph.add_node("receive_submission", receive_submission)
    graph.add_node("deliver_hint", deliver_hint)
    graph.add_node("run_qa_engineer", run_qa_engineer)
    graph.add_node("execute_via_mcp", execute_via_mcp)
    graph.add_node("deliver_feedback", deliver_feedback)
    graph.add_node("reteach", reteach)
    graph.add_node("run_judge", run_judge)

    # Phase 4: Session End
    graph.add_node("end_session", end_session)
    graph.add_node("update_mastery", update_mastery)

    # Fallback node (not in default flow but kept for programmatic use)
    graph.add_node("load_job_config", load_job_config)

    # --- Entry point: build_profile (Streamlit provides raw_job_description in initial state) ---
    graph.set_entry_point("build_profile")

    # Phase 1 edges
    graph.add_edge("build_profile", "generate_proxies")
    graph.add_edge("generate_proxies", "run_study_architect")

    # Phase 2 edges
    graph.add_edge("run_study_architect", "present_study_guide")
    graph.add_edge("present_study_guide", "ask_question")

    # Phase 3 edges
    graph.add_edge("deliver_hint", "receive_submission")
    graph.add_edge("run_qa_engineer", "execute_via_mcp")
    graph.add_edge("deliver_feedback", "receive_submission")
    graph.add_edge("reteach", "ask_question")

    # Phase 4 edges
    graph.add_edge("end_session", "update_mastery")
    graph.add_edge("update_mastery", END)

    # Conditional edges
    graph.add_conditional_edges(
        "ask_question",
        route_after_question,
        {
            "receive_submission": "receive_submission",
            "end_session": "end_session",
        },
    )
    graph.add_conditional_edges(
        "receive_submission",
        route_human_input,
        {
            "deliver_hint": "deliver_hint",
            "reteach": "reteach",
            "run_qa_engineer": "run_qa_engineer",
            "run_judge": "run_judge",  # Conceptual skill bypass
        },
    )
    graph.add_conditional_edges(
        "execute_via_mcp",
        evaluate_result,
        {
            "run_judge": "run_judge",
            "deliver_feedback": "deliver_feedback",
            "reteach": "reteach",
        },
    )
    graph.add_conditional_edges(
        "run_judge",
        route_after_judge,
        {
            "ask_question": "ask_question",
            "end_session": "end_session",
        },
    )

    return graph.compile(checkpointer=checkpointer)


workflow = build_workflow()
