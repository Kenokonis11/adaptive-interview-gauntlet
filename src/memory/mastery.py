"""Local mastery profile storage and update logic."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any


def update_skill_score(current_score: float, session_score: float, alpha: float = 0.3) -> float:
    """Apply the documented exponential moving average update."""

    return round(current_score * (1 - alpha) + session_score * alpha, 3)


def ensure_mastery_file(path: str = "data/user_mastery.json", skills: list[str] | None = None) -> dict[str, Any]:
    """Create or normalize the mastery file so it follows the documented schema."""

    mastery_path = Path(path)
    mastery_path.parent.mkdir(parents=True, exist_ok=True)

    if mastery_path.exists():
        try:
            existing = json.loads(mastery_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
    else:
        existing = {}

    skills = skills or []
    if not existing:
        existing = {
            "candidate_name": "",
            "last_updated": "",
            "sessions_completed": 0,
            "skills": {},
        }

    existing.setdefault("candidate_name", "")
    existing.setdefault("last_updated", "")
    existing.setdefault("sessions_completed", 0)
    existing.setdefault("skills", {})

    for skill in skills:
        existing["skills"].setdefault(
            skill,
            {"score": 0.0, "attempts": 0, "last_tested": None, "history": [0.0]},
        )

    mastery_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    return existing


def load_mastery_full_data(path: str = "data/user_mastery.json", skills: list[str] | None = None) -> dict[str, Any]:
    """Read mastery data without mutating disk during session start."""

    mastery_path = Path(path)
    skills = skills or []

    if mastery_path.exists():
        try:
            existing = json.loads(mastery_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
    else:
        existing = {}

    if not existing:
        existing = {
            "candidate_name": "",
            "last_updated": "",
            "sessions_completed": 0,
            "skills": {},
        }

    existing.setdefault("candidate_name", "")
    existing.setdefault("last_updated", "")
    existing.setdefault("sessions_completed", 0)
    existing.setdefault("skills", {})

    for skill in skills:
        existing["skills"].setdefault(
            skill,
            {"score": 0.0, "attempts": 0, "last_tested": None, "history": [0.0]},
        )

    return existing


def load_mastery(path: str = "data/user_mastery.json") -> dict[str, float]:
    """Load mastery scores using the documented read pattern."""

    if not Path(path).exists():
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    skills = data.get("skills", {})
    return {skill: float(info.get("score", 0.0)) for skill, info in skills.items()}


def write_mastery(
    path: str,
    deltas: dict[str, float],
    full_data: dict[str, Any],
    alpha: float = 0.3,
) -> None:
    """Apply mastery updates exactly once per session and persist the full profile."""

    full_data.setdefault("candidate_name", "")
    full_data.setdefault("last_updated", "")
    full_data.setdefault("sessions_completed", 0)
    full_data.setdefault("skills", {})

    mastery_path = Path(path)
    mastery_path.parent.mkdir(parents=True, exist_ok=True)

    for skill, new_score in deltas.items():
        if skill not in full_data["skills"]:
            full_data["skills"][skill] = {
                "score": 0.0,
                "attempts": 0,
                "last_tested": None,
                "history": [0.0],
            }

        entry = full_data["skills"][skill]
        entry.setdefault("score", 0.0)
        entry.setdefault("attempts", 0)
        entry.setdefault("last_tested", None)
        entry.setdefault("history", [0.0])

        entry["score"] = update_skill_score(float(entry["score"]), float(new_score), alpha=alpha)
        entry["attempts"] += 1
        entry["last_tested"] = dt.date.today().isoformat()
        entry["history"].append(entry["score"])

    full_data["last_updated"] = dt.datetime.now().isoformat()
    full_data["sessions_completed"] += 1
    mastery_path.write_text(json.dumps(full_data, indent=2), encoding="utf-8")
