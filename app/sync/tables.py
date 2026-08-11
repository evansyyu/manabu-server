from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from app.models import Favorite, Setting
from app.sync.schemas import FavoriteRow, SettingRow

SETTINGS_KEY_DENYLIST_PREFIXES = ("session_undo_boundary_",)


@dataclass(frozen=True)
class SyncedTable:
    name: str
    model: type[Any]
    row_schema: type[BaseModel]
    pk: tuple[str, ...]


TABLES: tuple[SyncedTable, ...] = (
    SyncedTable("favorites", Favorite, FavoriteRow, ("item_type", "item_id")),
    SyncedTable("settings", Setting, SettingRow, ("key",)),
)

TABLES_BY_NAME = {t.name: t for t in TABLES}


def is_denied_setting_key(key: str) -> bool:
    return key.startswith(SETTINGS_KEY_DENYLIST_PREFIXES)