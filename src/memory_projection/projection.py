from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from history import ProjectionSnapshot


_TERM_RE = re.compile(r"[A-Za-z0-9_-]{3,}")


@dataclass(frozen=True)
class MemoryRecord:
    object_id: str
    object_type: str
    object_hash: str
    state_ref: str
    searchable_text: str


@dataclass(frozen=True)
class MemoryHit:
    object_id: str
    object_type: str
    object_hash: str
    state_ref: str
    score: int
    searchable_text: str


class MemoryProjection:
    """Disposable retrieval projection over the canonical state snapshot.

    It has no method that admits facts, mutates epistemic objects, or commits
    state. Rebuilding it from the same snapshot yields the same record set.
    """

    def __init__(self) -> None:
        self._state_ref: str | None = None
        self._records: tuple[MemoryRecord, ...] = ()

    @property
    def state_ref(self) -> str | None:
        return self._state_ref

    @property
    def records(self) -> tuple[MemoryRecord, ...]:
        return self._records

    def rebuild(self, snapshot: ProjectionSnapshot) -> None:
        records = []
        for obj in snapshot.active_objects:
            # Canonical object content is an input to indexing, not copied into a
            # second authority-bearing store with independent lifecycle rules.
            text = " ".join(
                [obj.object_type, obj.object_id, obj.content_json]
            ).lower()
            records.append(
                MemoryRecord(
                    object_id=obj.object_id,
                    object_type=obj.object_type,
                    object_hash=obj.object_hash,
                    state_ref=snapshot.state_ref,
                    searchable_text=text,
                )
            )
        self._records = tuple(sorted(records, key=lambda x: x.object_id))
        self._state_ref = snapshot.state_ref

    def search(self, query: str, *, limit: int = 8, object_types: Iterable[str] | None = None) -> tuple[MemoryHit, ...]:
        if limit <= 0:
            return ()
        terms = {x.lower() for x in _TERM_RE.findall(query)}
        allowed = {x.upper() for x in object_types} if object_types is not None else None
        hits: list[MemoryHit] = []
        for record in self._records:
            if allowed is not None and record.object_type not in allowed:
                continue
            score = sum(1 for term in terms if term in record.searchable_text)
            if score <= 0 and terms:
                continue
            hits.append(
                MemoryHit(
                    object_id=record.object_id,
                    object_type=record.object_type,
                    object_hash=record.object_hash,
                    state_ref=record.state_ref,
                    score=score,
                    searchable_text=record.searchable_text,
                )
            )
        hits.sort(key=lambda x: (-x.score, x.object_id))
        return tuple(hits[:limit])
