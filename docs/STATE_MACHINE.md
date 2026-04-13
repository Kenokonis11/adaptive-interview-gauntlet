# STATE_MACHINE.md
## LangGraph State Machine — Nodes, Edges, and Triggers

---

### The State Object

```python
from typing import TypedDict, Optional, Literal
from pydantic import BaseModel

class MCPResult(BaseModel):
    exit_code: int           # 0 = pass, non-zero = fail
    tests_passed: int
    tests_total: int
    execution_time_ms: float
    stdout: str
    stderr: str
    traceback: Optional[str]

class SkillProxy(BaseModel):
    original_skill: str
    proxy_type: Literal["python_pandas", "sql_duckdb", "python_general"]
    proxy_context: str       # natural language description for the Hiring Manager
    test_dataset: str        # path or inline data for QA Engineer to use

class Question(BaseModel):
    text: str
    skill: str
    difficulty: Literal["warm_up", "standard", "stretch"]
    expected_concepts: list[str]   # for Judge to evaluate against

class InterviewState(TypedDict):
    # --- Session identity ---
    job_yaml_path: str
    target_company: str
    target_role: str
    session_id: str

    # --- Loaded from user_mastery.json at session start (READ ONLY during session) ---
    mastery: dict[str, float]      # {"pandas_merge": 0.4, "window_functions": 0.2}

    # --- Built by Study Architect ---
    job_requirements: list[str]
    study_guide: str               # markdown string
    skill_proxies: list[SkillProxy]

    # --- Active during interview loop ---
    current_question: Optional[Question]
    current_skill: str
    user_submission: Optional[str]     # raw code submitted by user
    attempt_count: int                 # resets to 0 per new question
    consecutive_failures: int          # triggers reteach at == 2
    mcp_result: Optional[MCPResult]
    session_transcript: list[dict]     # list of {role, content} dicts

    # --- Written only by Judge at session end ---
    mastery_deltas: dict[str, float]   # {"window_functions": +0.15}
    session_score: float               # 0.0 to 1.0
    judge_narrative: str               # prose summary of performance
```

**Critical constraint**: `mastery` is read-only during the session. No node except the final `update_mastery` node may write to `user_mastery.json`. `mastery_deltas` is the buffer — it accumulates during the session and is flushed at the very end.

---

### Nodes

#### `load_job_config`
- Reads the YAML file at `job_yaml_path`
- Populates `target_company`, `target_role`, `job_requirements`, `skill_proxies`
- Reads `user_mastery.json` and populates `mastery`
- No LLM call

#### `run_study_architect`
- LLM call (Study Architect system prompt)
- Input: `job_requirements`, `mastery`
- Output: `study_guide` (markdown), possibly reordered `skill_proxies` by priority
- Prioritizes skills where `mastery[skill] < 0.5`

#### `present_study_guide`
- HITL node — prints study guide to user, waits for acknowledgement
- User can type `start` to begin interview or `skip` to jump straight to questions
- No LLM call

#### `ask_question`
- LLM call (Hiring Manager system prompt)
- Selects next skill from `skill_proxies` (lowest mastery first)
- Generates `current_question` with appropriate difficulty
- Prints question to user, waits for code submission
- Sets `attempt_count = 0` if new question

#### `receive_submission`
- HITL node — captures user's submitted code into `user_submission`
- Also accepts `hint` command (triggers `deliver_hint` node)
- Also accepts `timeout` command (triggers `reteach` node immediately)

#### `run_qa_engineer`
- LLM call (QA Engineer system prompt)
- Input: `current_question`, `current_skill`, proxy test dataset
- Output: 5 hidden unit test cases as executable Python strings
- **Never outputs to user**

#### `execute_via_mcp`
- Calls MCP tool `execute_code_with_tests(user_code, test_cases)`
- Populates `mcp_result`
- Increments `attempt_count`
- No LLM call

#### `evaluate_result`
- Reads `mcp_result.exit_code`
- If pass: routes to `run_judge`
- If fail and `attempt_count < 2`: routes to `deliver_feedback`
- If fail and `attempt_count >= 2`: increments `consecutive_failures`, routes to `reteach`
- No LLM call — pure conditional logic

#### `deliver_feedback`
- LLM call (Hiring Manager system prompt, feedback mode)
- Input: `mcp_result` (specifically `stderr`, `traceback`, `tests_passed/total`)
- Output: Socratic hint — does NOT give the answer
- Example: "Your logic failed when the dataframe had missing user IDs. Think about null handling before the join. You have one more attempt."
- Routes back to `receive_submission`

#### `reteach`
- LLM call (Hiring Manager system prompt, tutor mode — different system prompt)
- Hiring Manager drops interviewer persona
- Walks through the exact failure using a whiteboard-style explanation
- Generates a simpler, related follow-up question at `warm_up` difficulty
- Routes to `ask_question` with the simpler question pre-loaded

#### `deliver_hint`
- LLM call (Hiring Manager system prompt, hint mode)
- Triggered by user typing `hint` during `receive_submission`
- Costs one attempt (`attempt_count += 1`)
- Routes back to `receive_submission`

#### `run_judge`
- LLM call (Judge system prompt)
- Input: full `session_transcript`, `current_question.expected_concepts`, `mcp_result`
- Output: skill-level score (0.0–1.0), delta from prior mastery, brief narrative
- Accumulates into `mastery_deltas`
- Routes to `ask_question` for next skill, or `end_session` if all skills complete

#### `end_session`
- LLM call (Judge system prompt, synthesis mode)
- Produces `session_score` and `judge_narrative`
- Prints performance summary to user

#### `update_mastery`
- Reads `mastery_deltas`, applies to `mastery`, writes to `user_mastery.json`
- **Only node that writes to disk**
- No LLM call

---

### Edge Map

```
load_job_config
    └──► run_study_architect
             └──► present_study_guide (HITL)
                      └──► ask_question
                               └──► receive_submission (HITL)
                                        ├── [hint] ──► deliver_hint ──► receive_submission
                                        ├── [timeout] ──► reteach ──► ask_question
                                        └── [code] ──► run_qa_engineer
                                                            └──► execute_via_mcp
                                                                     └──► evaluate_result
                                                                              ├── [pass] ──► run_judge
                                                                              │                  ├── [more skills] ──► ask_question
                                                                              │                  └── [done] ──► end_session ──► update_mastery
                                                                              ├── [fail, attempts < 2] ──► deliver_feedback ──► receive_submission
                                                                              └── [fail, attempts >= 2] ──► reteach ──► ask_question
```

---

### State Transition Triggers (Exact Conditions)

| Trigger | Condition | From Node | To Node |
|---|---|---|---|
| Reteach mode | `mcp_result.exit_code != 0` AND `attempt_count >= 2` | `evaluate_result` | `reteach` |
| Feedback loop | `mcp_result.exit_code != 0` AND `attempt_count < 2` | `evaluate_result` | `deliver_feedback` |
| Next question | `mcp_result.exit_code == 0` AND remaining skills exist | `run_judge` | `ask_question` |
| Session end | `mcp_result.exit_code == 0` AND no remaining skills | `run_judge` | `end_session` |
| Hint penalty | User types `hint` | `receive_submission` | `deliver_hint` |
| Immediate reteach | User types `timeout` | `receive_submission` | `reteach` |
