# EVALUATION_RUBRIC.md
## Evaluation Framework — How the Judge Scores, What Mastery Deltas Mean

---

### Philosophy

The evaluation framework has two jobs:
1. **Per-question scoring**: Did the candidate demonstrate understanding of this skill?
2. **Longitudinal mastery tracking**: Is the candidate improving across sessions?

The Judge agent never evaluates code correctness directly — that is the MCP's job. The Judge synthesizes the MCP result, the attempt history, and the question's expected concepts into a score.

---

### Per-Question Scoring Rubric

| Score | Criteria |
|---|---|
| 1.0 | Passed all 5 tests, first attempt, no hints, execution time reasonable |
| 0.85 | Passed all 5 tests, first attempt, one hint used |
| 0.75 | Passed all 5 tests, first attempt, execution time exceeded 5s (inefficient solution) |
| 0.65 | Passed all 5 tests, second attempt, no hints |
| 0.55 | Passed all 5 tests, second attempt, hint used |
| 0.45 | Failed twice; passed the reteach warm-up question on first attempt |
| 0.25 | Failed twice; passed the reteach warm-up question on second attempt |
| 0.1 | Failed twice; failed reteach but showed partial understanding (3+/5 tests passed) |
| 0.0 | Failed all attempts including reteach; fewer than 3/5 tests passed |

**Partial credit note**: If a candidate passes 3/5 or 4/5 tests, the Judge uses the ratio to interpolate within the relevant band rather than collapsing to the nearest bracket. Example: 4/5 tests + second attempt = 0.55 * (4/5) = 0.44.

---

### Mastery Delta Calculation

The Judge returns a `score` (0.0–1.0) for the session's performance on a skill. The `update_mastery` node applies this to the running mastery score using an exponential moving average:

```
new_mastery = old_mastery * (1 - alpha) + session_score * alpha
```

Default `alpha = 0.3`. This means:
- A single perfect session on a skill you scored 0.2 on brings you to: `0.2 * 0.7 + 1.0 * 0.3 = 0.44`
- A single failed session on a skill you scored 0.8 on brings you to: `0.8 * 0.7 + 0.0 * 0.3 = 0.56`

This is intentional — it prevents a bad day from erasing genuine competence, and it prevents one lucky session from inflating a weak skill.

---

### Session-Level Evaluation (LLM-as-Judge)

After all skills are covered, the Judge produces a session synthesis. This is the only place the LLM-as-judge role is fully exercised — the Judge reads the full session transcript and evaluates qualitative dimensions that the MCP cannot measure:

**Dimensions evaluated by the Judge (narrative only, not scored)**:
- Did the candidate's explanation in comments/variable names reflect understanding, or just trial-and-error?
- Did the candidate ask clarifying questions (via the `hint` command) strategically or desperately?
- Was there evidence of generalizing concepts (e.g., applying window function logic to a novel case)?

These qualitative observations appear in `judge_narrative` and are presented to the user at session end. They do not affect mastery scores directly — they inform the next session's study guide.

---

### RAGAS Integration (Stretch Goal — Post-MVP)

For evaluating whether the QA Engineer's test cases are well-aligned with the Hiring Manager's question intent, RAGAS `answer_relevancy` can be applied:

- **Context**: The question text + expected concepts
- **Answer**: The QA Engineer's generated test cases (as prose descriptions)
- **Metric**: `answer_relevancy` score — does the test suite actually probe the concepts the question was meant to test?

If RAGAS score < 0.6, the system flags the test suite as potentially misaligned and logs it for review. This does not block execution — it's a quality monitoring signal.

Implementation: run RAGAS evaluation async after each session, log results to `data/eval_log.jsonl`. Review manually.

---

### What the Evaluation Framework Demonstrates to a Professor

1. **LLM-as-judge is load-bearing**: The Judge isn't cosmetic. Its output directly mutates the mastery JSON which changes subsequent session behavior.
2. **Deterministic vs non-deterministic boundary is explicit**: MCP handles correctness (deterministic). Judge handles quality and synthesis (non-deterministic). These are never mixed.
3. **Longitudinal evaluation**: The system can demonstrate before/after mastery curves across multiple demo sessions — visible, quantifiable improvement.
4. **Adversarial test generation**: The QA Engineer's tests are generated fresh per question and are never shown to the candidate. This is structurally anti-sycophantic.
