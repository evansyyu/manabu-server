from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from app.models import (
    Favorite,
    Setting,
    SrsBlacklist,
    SrsItem,
    SrsReviewLog,
    StudySet,
    StudySetWord,
)
from app.sync.schemas import (
    FavoriteRow,
    SettingRow,
    SrsBlacklistRow,
    SrsItemRow,
    SrsReviewLogRow,
    StudySetRow,
    StudySetWordRow,
)

SETTINGS_KEY_DENYLIST_PREFIXES = ("session_undo_boundary_",)


@dataclass(frozen=True)
class SyncedTable:
    name: str
    model: type[Any]
    row_schema: type[BaseModel]
    pk: tuple[str, ...]

    @property
    def wire_columns(self) -> tuple[str, ...]:
        """Columns sent to clients on pull — the push schema's fields.

        Deriving this from row_schema keeps push and pull in lockstep and
        keeps server-only columns (user_id, server_seq, server_updated_at,
        last_device_id) off the wire.
        """
        return tuple(self.row_schema.model_fields)


TABLES: tuple[SyncedTable, ...] = (
    SyncedTable("favorites", Favorite, FavoriteRow, ("item_type", "item_id")),
    SyncedTable("settings", Setting, SettingRow, ("key",)),
    SyncedTable("study_sets", StudySet, StudySetRow, ("id",)),
    SyncedTable(
        "study_set_words", StudySetWord, StudySetWordRow, ("set_id", "word_id")
    ),
    SyncedTable(
        "srs_item", SrsItem, SrsItemRow, ("category", "item_id", "card_type")
    ),
    SyncedTable(
        "srs_blacklist", SrsBlacklist, SrsBlacklistRow, ("category", "item_id")
    ),
    SyncedTable("srs_review_log", SrsReviewLog, SrsReviewLogRow, ("id",)),
)

TABLES_BY_NAME = {t.name: t for t in TABLES}


def is_denied_setting_key(key: str) -> bool:
    return key.startswith(SETTINGS_KEY_DENYLIST_PREFIXES)