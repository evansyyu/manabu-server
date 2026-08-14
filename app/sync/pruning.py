"""Tombstone pruning (manabu-db-spec.md §3.2): deletes stop being rows.

A tombstone's job is to out-race every device that might still resurrect the
deleted row. After a grace period comfortably longer than any plausible
offline gap, that race is over and the tombstone is dead weight — pruned
here. The documented, accepted risk: a device offline *longer* than the
grace window can re-push a stale live row and resurrect it (spec §3.2); 90
days makes that vanishingly rare.

Two shapes of tombstone:
  - srs_item_tombstone rows (the whole row IS the tombstone) — deleted.
  - deleted_at-marked rows on the LWW tables — hard-deleted.

Run opportunistically per user on every push. No throttle: five bounded
DELETEs on user-scoped indexes, trivial at this scale; a last-pruned-at
throttle is the obvious upgrade if it ever shows in timings.

The client prunes its own copies on the same 90-day clock (lib/sync/prune.ts
in the app repo) — pruning only one side would leave the other re-uploading
ancient tombstones forever.
"""

import time

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Favorite,
    SrsBlacklist,
    SrsItemTombstone,
    StudySet,
    StudySetWord,
)

TOMBSTONE_GRACE_DAYS = 90
_GRACE_MS = TOMBSTONE_GRACE_DAYS * 24 * 60 * 60 * 1000

_SOFT_DELETED_MODELS = (Favorite, StudySet, StudySetWord, SrsBlacklist)


async def prune_tombstones(
    session: AsyncSession, user_id, now_ms: int | None = None
) -> None:
    cutoff = (now_ms if now_ms is not None else int(time.time() * 1000)) - _GRACE_MS

    await session.execute(
        delete(SrsItemTombstone).where(
            SrsItemTombstone.user_id == user_id,
            SrsItemTombstone.deleted_at < cutoff,
        )
    )
    for model in _SOFT_DELETED_MODELS:
        await session.execute(
            delete(model).where(
                model.user_id == user_id,
                model.deleted_at.is_not(None),
                model.deleted_at < cutoff,
            )
        )
