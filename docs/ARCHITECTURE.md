# ARCHITECTURE.md
## Adaptive Interview Gauntlet — System Overview

---

### What This System Is

A locally-executed, multi-agent technical interview simulator that:
- Ingests a job config (YAML) describing a target role and its required skills
- Produces a personalized study guide and testable question set
- Executes submitted code deterministically via a sandboxed MCP server
- Recursively re-teaches concepts on failure, rather than just marking wrong
- Tracks candidate mastery longitudinally across sessions via a persistent JSON profile

This system is **not** a chatbot wrapper. The core value proposition is that an LLM cannot grade its own code — the MCP sandbox does that. The LLM handles creativity (question generation, tutoring, synthesis). Python handles correctness (execution, test results, mastery math).

---

### High-Level Data Flow

```
[Job YAML] ──► [Study Architect] ──► [Skill Proxies]
                                           │
                                    [Hiring Manager] ◄──── [user_mastery.json]
                                           │
                                     [User submits code]
                                           │
                                      [QA Engineer]
                                           │
                                    [MCP: execute_code_with_tests()]
                                           │
                              ┌────────────┴────────────┐
                           pass                        fail (×2)
                              │                           │
                        [Judge Agent]            [Reteach Mode]
                              │                           │
                    [mastery_deltas]              [easier proxy]
                              │
                    [user_mastery.json updated]
```

---

### Agent Roles (Hard Boundaries)

| Agent | Responsibility | Forbidden From |
|---|---|---|
| Study Architect | Parse job YAML, generate study guide, produce skill proxies | Evaluating code, updating mastery |
| Hiring Manager | Conduct the interview, deliver questions, manage state, deliver feedback | Executing code, judging correctness |
| QA Engineer | Write hidden unit tests, call MCP tool, return structured result | Speaking to user directly |
| Judge | Score session performance, compute mastery deltas, write to JSON | Asking questions, generating test cases |

The QA Engineer and Hiring Manager are the critical separation. The Hiring Manager is **strictly forbidden** from evaluating whether code is correct. It only sees the structured output from the MCP result.

---

### Technology Stack

| Layer | Choice | Rationale |
|---|---|---|
| Orchestration | LangGraph | State machine with explicit node/edge routing; enforces agent boundaries |
| Output parsing | Pydantic | Typed agent outputs prevent hallucinated structure |
| LLM backend | Any OpenAI-compatible endpoint | Swappable; default to GPT-4o or Claude |
| Code execution | Python subprocess (restricted) | Fast to build, honest about what it does |
| SQL execution | DuckDB in-process | No server needed; full SQL support including window functions |
| Mastery storage | `user_mastery.json` (local file) | Simple, portable, human-readable |
| Job config | YAML files per target role | Easy to extend; no DB needed for MVP |
| Vector store (RAG) | ChromaDB (local) | Session context + prior question history |

---

### Directory Structure

```
gauntlet/
├── agents/
│   ├── study_architect.py
│   ├── hiring_manager.py
│   ├── qa_engineer.py
│   └── judge.py
├── graph/
│   ├── state.py            # InterviewState TypedDict
│   ├── nodes.py            # LangGraph node functions
│   └── edges.py            # Conditional routing logic
├── mcp/
│   ├── server.py           # MCP server entry point
│   ├── executor.py         # Python subprocess runner
│   └── sql_executor.py     # DuckDB runner
├── memory/
│   ├── mastery.py          # Read/write user_mastery.json
│   └── vector_store.py     # ChromaDB session context
├── configs/
│   └── acme_data_scientist.yaml   # MVP job config
├── data/
│   └── user_mastery.json   # Persistent mastery profile
├── docs/                   # This directory
└── main.py                 # Entry point
```

---

### What Makes This Better Than Booting Up an LLM

1. **Deterministic correctness**: Code is executed. Pass/fail is not a guess.
2. **Adversarial test generation**: The QA Engineer writes tests the user never sees. Sycophancy is architecturally impossible.
3. **Longitudinal mastery**: The system remembers what you struggled with last session and prioritizes it.
4. **Role-specific grounding**: Questions are derived from job YAML context, not generic LeetCode.
5. **Recursive reteaching**: Failure triggers a mode shift — not just "wrong, try again."
