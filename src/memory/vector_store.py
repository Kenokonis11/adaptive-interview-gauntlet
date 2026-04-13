"""Question memory store backed by persistent ChromaDB."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import chromadb


CHROMA_PATH = Path(__file__).resolve().parents[2] / "data" / "chroma_db"
COLLECTION_NAME = "asked_questions"


def _get_collection():
    CHROMA_PATH.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    return client.get_or_create_collection(COLLECTION_NAME)


def log_question(skill: str, question_text: str) -> None:
    """Persist a previously asked question for future retrieval."""

    if not skill or not question_text:
        return

    collection = _get_collection()
    collection.add(
        ids=[str(uuid.uuid4())],
        documents=[question_text],
        metadatas=[{"skill": skill}],
    )


def get_previous_questions(skill: str) -> list[str]:
    """Return previously asked questions for a given skill."""

    if not skill:
        return []

    collection = _get_collection()
    results = collection.get(where={"skill": skill}, include=["documents"])
    documents = results.get("documents", [])
    flattened = _flatten_documents(documents)
    return list(dict.fromkeys(flattened))


def _flatten_documents(documents: Any) -> list[str]:
    if isinstance(documents, str):
        return [documents]
    if isinstance(documents, list):
        flattened: list[str] = []
        for item in documents:
            flattened.extend(_flatten_documents(item))
        return flattened
    return []
