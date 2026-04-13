"""Main entry point for the Adaptive Interview Gauntlet.

Loads the state, compiles the workflow, and executes the interview loop.
"""

import os
import asyncio
from typing import Any

# TODO: start MCP server as subprocess before graph compile

from src.graph.workflow import workflow

def setup_environment():
    """Ensure essential environment variables are set."""
    if not os.getenv("GAUNTLET_MODEL"):
        os.environ["GAUNTLET_MODEL"] = "google-gla:gemini-2.0-flash"
    
    # Map GEMINI_API_KEY to GOOGLE_API_KEY if pydantic-ai expects it.
    if os.getenv("GEMINI_API_KEY") and not os.getenv("GOOGLE_API_KEY"):
        os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]
    
    # Check for the key pydantic-ai actually needs for 'google-gla'
    if not os.getenv("GOOGLE_API_KEY"):
        print("WARNING: GOOGLE_API_KEY (or GEMINI_API_KEY) is not set. Agents will fail to run.")

def run_interview():
    """Initialize and run the LangGraph workflow."""
    
    # Initial state
    initial_state = {
        "job_yaml_path": "configs/acme_data_scientist.yaml",
        "session_transcript": [],
        "mastery_deltas": {},
        "question_history": [],
    }
    
    print("--- Starting Adaptive Interview Gauntlet ---")
    
    # Run the workflow until completion.
    # The CLI entry point assumes required human-in-the-loop state is supplied externally.
    
    try:
        # LangGraph workflow.invoke() runs the graph to completion (END)
        # It handles the iteration between nodes based on edges.
        final_state = workflow.invoke(initial_state)
        
        print("\n--- Session Complete ---")
        print(f"Final Score: {final_state.get('session_score', 0.0)}")
        print("\nJudge's Narrative:")
        print(final_state.get("judge_narrative", "No narrative provided."))
        
    except Exception as e:
        print(f"\nAn error occurred during the interview: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    setup_environment()
    run_interview()
