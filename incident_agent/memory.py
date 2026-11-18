"""
incident_agent/memory.py
------------------------
Three-layer memory for the incident investigator (Step 4 of the roadmap):

1. Working memory  — the LLM context window; curated by context engineering
   (scratchpad + compaction) so only high-signal facts enter it.
2. Session memory  — :class:`Scratchpad`, a bounded per-investigation note
   store the reason-act-observe loop appends to.
3. Long-term memory — :class:`IncidentMemory`, a SQLite store of solved
   incidents retrievable by service/keyword similarity for future runs.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

MAX_SCRATCHPAD_NOTES = 24
SCRATCHPAD_NOTE_MAX_CHARS = 400
DEFAULT_MAX_CONTEXT_TOKENS = 4000
TRUNCATION_MARKER = "...[compacted]"


def _default_db_path() -> Path:
    """
    Resolve the SQLite store location: ``INCIDENT_MEMORY_DB`` env var when set,
    else a ``data/`` directory beside the package (never next to the source
    files, so importing the package never drops a DB into the repo tree).
    """
    override = os.getenv("INCIDENT_MEMORY_DB")
    if override:
        return Path(override)
    data_dir = Path(__file__).resolve().parent.parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "incident_memory.db"


_DB_PATH = _default_db_path()


# ---------------------------------------------------------------------------
# Layer 2: session memory (scratchpad)
# ---------------------------------------------------------------------------


class Scratchpad:
    """
    Bounded per-investigation scratchpad. The loop appends structured notes
    (observations, hypotheses, evidence pointers); the scratchpad is what
    survives across loop iterations without re-reading raw tool output.
    """

    def __init__(self, max_notes: int = MAX_SCRATCHPAD_NOTES):
        self.max_notes = max_notes
        self._notes: List[Dict[str, Any]] = []

    def add(self, note: str, kind: str = "observation") -> None:
        text = (note or "").strip()
        if not text:
            return
        if len(text) > SCRATCHPAD_NOTE_MAX_CHARS:
            text = text[: SCRATCHPAD_NOTE_MAX_CHARS - len(TRUNCATION_MARKER)] + TRUNCATION_MARKER
        self._notes.append({"kind": kind, "text": text})
        if len(self._notes) > self.max_notes:
            # Drop oldest low-signal observations first, keep hypotheses.
            for i, n in enumerate(self._notes):
                if n["kind"] == "observation":
                    del self._notes[i]
                    break
            else:
                self._notes.pop(0)

    def notes(self) -> List[Dict[str, Any]]:
        return list(self._notes)

    def render(self) -> str:
        if not self._notes:
            return "(scratchpad empty)"
        lines = []
        for n in self._notes:
            lines.append(f"- [{n['kind']}] {n['text']}")
        return "\n".join(lines)

    def clear(self) -> None:
        self._notes.clear()


# ---------------------------------------------------------------------------
# Context engineering: compaction of raw tool output
# ---------------------------------------------------------------------------


def estimate_tokens(text: str) -> int:
    """Deterministic ~4 chars/token heuristic (matches TokenCircuitBreaker)."""
    if not text:
        return 0
    return max(len(text.split()), (len(text) + 3) // 4)


def compact_output(raw: str, max_chars: int = 2000) -> str:
    """
    Deterministic, token-bounded compaction: keep the head (usually the most
    relevant structured summary) and a bounded tail, with an explicit marker so
    the model knows context was elided rather than silently dropped.
    """
    text = raw or ""
    if len(text) <= max_chars:
        return text
    head = max_chars // 2
    # Account for the marker and the two surrounding newlines so the compacted
    # output never exceeds max_chars.
    tail = max_chars - head - len(TRUNCATION_MARKER) - 2
    return text[:head] + "\n" + TRUNCATION_MARKER + "\n" + text[-tail:]


# ---------------------------------------------------------------------------
# Layer 3: long-term memory (SQLite solved-incident store)
# ---------------------------------------------------------------------------


class IncidentMemory:
    """
    SQLite long-term store of solved incidents. Semantic-ish retrieval is
    implemented deterministically (service match + token overlap) so the agent
    works offline with no embedding dependency, mirroring the repository's
    hermetic-test convention.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path is not None else _DB_PATH
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS solved_incidents (
                incident_id TEXT PRIMARY KEY,
                service TEXT NOT NULL,
                title TEXT NOT NULL,
                root_cause_change_id TEXT,
                root_cause_hypothesis TEXT,
                resolution TEXT,
                solved_at TEXT NOT NULL,
                fingerprint TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    # -- write path ---------------------------------------------------------

    def record_solved(
        self,
        incident_id: str,
        service: str,
        title: str,
        root_cause_change_id: Optional[str],
        root_cause_hypothesis: str,
        resolution: str,
        solved_at: str,
    ) -> None:
        fingerprint = hashlib.sha256(
            f"{incident_id}|{service}|{title}|{root_cause_change_id}".encode()
        ).hexdigest()[:16]
        self._conn.execute(
            """
            INSERT INTO solved_incidents
                (incident_id, service, title, root_cause_change_id,
                 root_cause_hypothesis, resolution, solved_at, fingerprint)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(incident_id) DO UPDATE SET
                service=excluded.service, title=excluded.title,
                root_cause_change_id=excluded.root_cause_change_id,
                root_cause_hypothesis=excluded.root_cause_hypothesis,
                resolution=excluded.resolution, solved_at=excluded.solved_at,
                fingerprint=excluded.fingerprint
            """,
            (incident_id, service, title, root_cause_change_id,
             root_cause_hypothesis, resolution, solved_at, fingerprint),
        )
        self._conn.commit()

    # -- read path ----------------------------------------------------------

    def retrieve_similar(
        self, service: str, title: str, top_k: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Deterministic similarity retrieval: exact service match scores highest,
        then token overlap between the query title and stored titles.
        """
        query_tokens = _tokens(title)
        rows = self._conn.execute(
            "SELECT incident_id, service, title, root_cause_change_id, "
            "root_cause_hypothesis, resolution, solved_at FROM solved_incidents"
        ).fetchall()
        scored: List[tuple[int, int, Dict[str, Any]]] = []
        for (
            iid, svc, ttl, change_id, hypothesis, resolution, solved_at
        ) in rows:
            score = 0
            if svc == service:
                score += 10
            title_tokens = _tokens(ttl)
            overlap = len(query_tokens & title_tokens)
            score += overlap
            if score > 0:
                scored.append((score, overlap, {
                    "incident_id": iid,
                    "service": svc,
                    "title": ttl,
                    "root_cause_change_id": change_id,
                    "root_cause_hypothesis": hypothesis,
                    "resolution": resolution,
                    "solved_at": solved_at,
                }))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [entry for _score, _overlap, entry in scored[:top_k]]

    def all(self) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT incident_id, service, title, root_cause_change_id, "
            "root_cause_hypothesis, resolution, solved_at FROM solved_incidents"
        ).fetchall()
        return [
            {
                "incident_id": r[0], "service": r[1], "title": r[2],
                "root_cause_change_id": r[3], "root_cause_hypothesis": r[4],
                "resolution": r[5], "solved_at": r[6],
            }
            for r in rows
        ]

    def close(self) -> None:
        self._conn.close()


def _tokens(text: str) -> set:
    import re
    return {
        tok
        for tok in re.findall(r"[a-z0-9]{3,}", (text or "").lower())
        if tok not in {"the", "and", "for", "with", "from", "after", "over"}
    }
