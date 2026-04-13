# MASTERY_SCHEMA.md
## user_mastery.json — Structure, Update Logic, and Conventions

---

### File Location

```
gauntlet/data/user_mastery.json
```

Created automatically on first run if it does not exist (all skills initialized to 0.0).

---

### Schema

```json
{
  "candidate_name": "string — optional, for display",
  "last_updated": "ISO 8601 datetime string",
  "sessions_completed": 3,
  "skills": {
    "pandas_merge": {
      "score": 0.75,
      "attempts": 4,
      "last_tested": "2024-03-15",
      "history": [0.0, 0.4, 0.6, 0.75]
    },
    "window_functions_sql": {
      "score": 0.2,
      "attempts": 1,
      "last_tested": "2024-03-15",
      "history": [0.0, 0.2]
    },
    "null_handling_pandas": {
      "score": 0.0,
      "attempts": 0,
      "last_tested": null,
      "history": [0.0]
    }
  }
}
```

---

### Score Semantics

| Range | Meaning | Study Architect behavior |
|---|---|---|
| 0.0 | Never tested | Always prioritize; use warm-up difficulty |
| 0.0–0.3 | Demonstrated weakness | High priority; start at warm-up |
| 0.3–0.6 | Partial understanding | Medium priority; standard difficulty |
| 0.6–0.8 | Solid grasp | Low priority; stretch difficulty if time permits |
| 0.8–1.0 | Strong | Skip unless job requires it explicitly |

---

### Update Logic

The `update_mastery` node (final node in graph) applies deltas using an exponential moving average to prevent a single bad session from destroying a high score:

```python
def update_skill_score(current_score: float, session_score: float, alpha: float = 0.3) -> float:
    """
    Weighted update: new sessions count for 30%, history for 70%.
    Prevents catastrophic forgetting from one bad day.
    """
    return round(current_score * (1 - alpha) + session_score * alpha, 3)
```

The `alpha = 0.3` is the default. It can be overridden in the job YAML if a more aggressive update is desired.

---

### Read Pattern (session start)

```python
def load_mastery(path: str = "data/user_mastery.json") -> dict:
    if not os.path.exists(path):
        return {}   # Study Architect treats all missing skills as 0.0
    with open(path) as f:
        data = json.load(f)
    return {skill: info["score"] for skill, info in data["skills"].items()}
```

---

### Write Pattern (session end only)

```python
def write_mastery(path: str, deltas: dict[str, float], full_data: dict) -> None:
    for skill, new_score in deltas.items():
        if skill not in full_data["skills"]:
            full_data["skills"][skill] = {"score": 0.0, "attempts": 0, "last_tested": None, "history": [0.0]}
        entry = full_data["skills"][skill]
        entry["score"] = update_skill_score(entry["score"], new_score)
        entry["attempts"] += 1
        entry["last_tested"] = datetime.date.today().isoformat()
        entry["history"].append(entry["score"])
    full_data["last_updated"] = datetime.datetime.now().isoformat()
    full_data["sessions_completed"] += 1
    with open(path, "w") as f:
        json.dump(full_data, f, indent=2)
```

**This function is called exactly once per session, from `update_mastery` node only.**

---

### How the RAG Layer Uses Mastery

ChromaDB stores embeddings of every question asked in prior sessions, keyed by skill. Before generating a new question, the Hiring Manager queries:

```python
results = chroma_collection.query(
    query_texts=[current_skill],
    where={"skill": current_skill},
    n_results=3
)
# Returns: prior questions asked for this skill
# Hiring Manager is instructed not to repeat these questions
```

This ensures genuine variety across sessions, not just the same three questions recycled.
