# 🧠 Adaptive Learning Gauntlet

A multi-agent AI learning platform that reads any job description and builds a personalized, end-to-end practice session — from personalized study guide to live code execution — in under a minute.

Paste a JD. The system extracts the exact skills the role requires, generates a study guide written for that specific stack, then asks practice questions and **executes your code against hidden unit tests** to give you deterministic, LLM-opinion-free feedback.

---

## Quick Start

### 1. Set your API Key

```powershell
# Windows PowerShell
$env:GOOGLE_API_KEY = "your-google-api-key-here"
```

```bash
# macOS / Linux
export GOOGLE_API_KEY="your-google-api-key-here"
```

A [Google AI Studio](https://aistudio.google.com/) key with access to **Gemini 2.5 Flash** is required. The free tier works; transient 503s are handled automatically by the UI with a **Try Again** button that resumes from the last checkpoint without restarting your session.

### 2. Install Dependencies

```bash
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS / Linux

pip install -r requirements.txt
```

### 3. Run the App

```bash
streamlit run streamlit_app.py
```

---

## How It Works

### Step 1 — Paste Any Job Description

Drop in a real JD — data science, ML engineering, frontend, whatever. The **Profile Builder** agent reads it and extracts 3–6 concrete, testable technical skills, classified into three categories:

| Category | Evaluation Method |
|---|---|
| `executable_python` | Code executed in the deterministic MCP sandbox |
| `executable_sql` | Query executed against an in-process DuckDB instance |
| `conceptual` | Response evaluated by the LLM Judge |

### Step 2 — Three-Agent Build Pipeline (~20–40 seconds)

```
Profile Builder → Proxy Generator → Study Architect
```

**Profile Builder** extracts skills from the raw JD text with job context preserved per skill ("The JD requires building data pipelines that join multi-source activity logs...").

**Proxy Generator** converts each extracted skill into an executable test proxy — a concrete practice scenario with an exact function signature, DataFrame/SQL schemas with column types, and a numbered list of hard requirements the hidden tests will enforce. No vague "write a function that does X."

**Study Architect** generates a personalized study guide in markdown, tailored to what the JD actually requires and what you said you're weak at. Includes worked code examples for every executable skill. Prioritizes the gaps you explicitly called out.

### Step 3 — Practice Loop

For each skill, the **Hiring Manager** agent formulates a precise question directly from the proxy context — including the exact function signature, input/output column schemas, and what the hidden tests check. You write your answer in the editor.

**For Python and SQL skills**, your code is executed by the MCP sandbox:

- A **QA Engineer** agent generates 5 hidden unit tests (happy path, null handling, edge case, duplicates, shape/grain)
- The **MCP executor** runs each test in an isolated subprocess with a restricted import sandbox
- Results come back as a pass/fail grid — per test, with collapsible error traces — not just a score

**For conceptual skills** (statistics, system design, React, cloud, etc.), your written response goes directly to the **Judge** for LLM evaluation against the expected concepts.

After each skill, the **Judge** scores your performance deterministically (executable) or via LLM rubric (conceptual) and updates your **mastery profile** using an exponential moving average that persists across sessions.

---

## Architecture

```
Intake Form (JD + experience notes)
  ↓
Profile Builder          — LLM: extracts skills + categories from raw JD
  ↓
Proxy Generator          — LLM: builds exact test scenarios (signatures, schemas, requirements)
  ↓
Study Architect          — LLM: writes personalized study guide with worked examples
  ↓
present_study_guide      — LangGraph INTERRUPT: user reads, clicks Start
  ↓
┌──────────────────────────────────────────────────────────────┐
│  Per-Skill Practice Loop (LangGraph state machine)           │
│                                                              │
│  Hiring Manager → QA Engineer → MCP Executor → Judge        │
│       ↑              (5 hidden tests)    (deterministic)     │
│       │                                                      │
│  receive_submission (INTERRUPT) — user submits / hints       │
│       │                                                      │
│  deliver_hint / reteach → Hiring Manager (tutor mode)        │
└──────────────────────────────────────────────────────────────┘
  ↓
Session Judge            — LLM: end-of-session narrative + priority
  ↓
Mastery Update           — EMA write to data/user_mastery.json
```

### The LangGraph State Machine

The entire session is a compiled LangGraph graph with 14 nodes, a `MemorySaver` checkpointer, and two `interrupt()` points — one after the study guide, one waiting for each submission. This means:

- The session is **fully resumable** — if Gemini returns a 503, the **Try Again** button resumes from the last checkpoint, not from scratch
- Hint and Reteach are proper graph branches — the Hiring Manager re-enters in a different prompt mode, not a hacky if/else in the UI
- Mastery is written exactly once at session end, not incremented on every answer

### The MCP Execution Sandbox

The MCP executor is a purpose-built **Model Context Protocol** server that runs candidate code in isolated subprocesses. Each test case is a `(setup_code, user_code, assertion_code)` triple — the QA Engineer generates the assertion layer that the candidate never sees.

Security controls:
- Network imports (`requests`, `urllib`, `socket`) are blocked at the AST level before execution
- File writes are intercepted by a patched `open()` builtin
- Each test runs in a fresh subprocess with a configurable timeout (default 10s)
- All 5 tests run to completion — no early exit on first failure — so you see the full pass/fail grid

The SQL path runs DuckDB in-process. The QA Engineer generates schema setup + validation queries; the executor runs them and checks result shapes and values.

### Mastery Memory

Skill scores persist in `data/user_mastery.json` and update each session via an **exponential moving average**:

```
new_score = alpha * session_score + (1 - alpha) * prior_score
```

The default `alpha = 0.3` weights recent performance while preserving historical signal. Scores compound across sessions — come back after studying a weak skill and watch it move.

The vector store (ChromaDB) logs every question asked per skill and prevents the Hiring Manager from repeating questions across sessions.

### Multi-Agent Roles

| Agent | Role | Output Type |
|---|---|---|
| **Profile Builder** | Extracts skills + categories from raw JD | `DynamicJobProfile` (structured) |
| **Proxy Generator** | Builds exact test proxies per skill | `GeneratedProxyList` (structured) |
| **Study Architect** | Personalizes study guide with examples | `StudyGuideResult` (structured) |
| **Hiring Manager** | Asks questions; delivers hints and tutor mode | Plain text |
| **QA Engineer** | Generates 5 hidden unit tests per question | `QATestCases` (structured) |
| **Judge** | Scores answers; writes session narrative | `QuestionScore`, `SessionReport` |

Structured agents use pydantic-ai's `output_type` to enforce schema at the LLM output level — if the model returns malformed JSON, the agent retries automatically.

### Hint and Reteach Escalation

The Hiring Manager has three modes per skill:

1. **Attempt 1** — Precise question: exact signature, schemas, numbered requirements. No ambiguity about what's being tested.
2. **Attempt 2 (Hint)** — One concrete, actionable fix. Not Socratic nudging. If your code failed with `KeyError: 'user_id'`, the hint says *"change `on='patient_id'` to `on='user_id'`"*, not *"think about your join key."*
3. **Attempt 3 (Reteach)** — Tutor mode: diagnose what went wrong → teach the concept with a worked example → give a simpler follow-up question with a new exact signature.

For conceptual skills, the same escalation applies without the sandbox: the judge evaluates your written response, and if insufficient, the Hiring Manager teaches the concept and asks a more focused follow-up.

---

## Project Structure

```
├── streamlit_app.py              # Streamlit UI — intake form, study guide, question loop
├── requirements.txt
├── .gitignore
│
├── configs/
│   └── acme_data_scientist.yaml  # YAML config entrypoint (alternative to JD paste)
│
├── data/
│   └── user_mastery.json         # Persisted skill scores across sessions
│
├── src/
│   ├── agents/
│   │   ├── _runtime.py           # pydantic-ai wrappers: run_text, run_structured, fallback logic
│   │   ├── schemas.py            # Shared Pydantic schemas: ExtractedSkill, QATestCases, QuestionScore
│   │   ├── profile_builder.py    # Extracts skills from raw JD text
│   │   ├── proxy_generator.py    # Builds executable test proxies per skill
│   │   ├── study_architect.py    # Generates personalized study guide
│   │   ├── hiring_manager.py     # Question / hint / tutor prompts
│   │   ├── qa_engineer.py        # Hidden unit test generation
│   │   └── judge.py              # Per-question + session scoring
│   │
│   ├── graph/
│   │   ├── state.py              # InterviewState TypedDict + MCPResult, SkillProxy, Question models
│   │   ├── nodes.py              # All 14 LangGraph node functions
│   │   ├── edges.py              # Conditional routing: route_human_input, evaluate_result
│   │   └── workflow.py           # Graph compilation with MemorySaver checkpointer
│   │
│   ├── mcp/
│   │   ├── executor.py           # Python sandbox: AST security scan + subprocess isolation
│   │   ├── sql_executor.py       # DuckDB SQL executor with per-test validation queries
│   │   ├── server.py             # MCP server exposing execute_python / execute_sql tools
│   │   └── client.py             # MCP client for tool calls
│   │
│   └── memory/
│       ├── mastery.py            # EMA mastery read/write against user_mastery.json
│       ├── vector_store.py       # ChromaDB question log: deduplication across sessions
│       └── store.py              # Generic store utilities
```

---

## Dependencies

| Package | Purpose |
|---|---|
| `streamlit` | Web UI framework |
| `langgraph` | State machine graph with checkpointing and `interrupt()` for human-in-the-loop |
| `pydantic-ai[google]` | Agent framework — Gemini provider, structured output, automatic retry |
| `mcp` | Model Context Protocol — server/client for sandboxed tool calls |
| `duckdb` | In-process SQL execution for window functions, joins, CTEs |
| `chromadb` | Vector store for question history deduplication across sessions |
| `pyyaml` | YAML config parsing |

---

## GenAI Concepts Demonstrated

**Multi-agent orchestration** — Six specialized agents with distinct roles and output schemas, coordinated by a LangGraph state machine. Agents never share mutable state directly; all communication flows through the typed `InterviewState`.

**Structured outputs** — Every agent that produces data (not prose) uses pydantic-ai's `output_type` to enforce a Pydantic schema at inference time. The QA Engineer cannot return malformed test cases; the Judge cannot return a score outside `[0.0, 1.0]`.

**Human-in-the-loop** — LangGraph's `interrupt()` suspends graph execution at the submission node, preserving full state in the `MemorySaver` checkpointer. Resumption happens with `Command(resume=value)` — the graph picks up exactly where it left off.

**LLM-as-eval** — For conceptual skills, the Judge implements a structured rubric evaluation: the LLM reads the question, expected concepts, and candidate response, then returns a calibrated score with a narrative. This is the evaluation path for anything that can't be sandboxed — statistics, system design, React patterns, cloud architecture.

**Neuro-symbolic hybrid** — Executable skills combine neural reasoning (LLM generates questions and tests) with deterministic verification (sandbox executes code, checks assertions). Correctness is never a matter of LLM opinion — the tests either pass or they don't.

**RAG for deduplication** — ChromaDB stores every question asked per skill. The Hiring Manager receives the vector-retrieved list of previous questions as context and is explicitly instructed not to repeat them across sessions.
