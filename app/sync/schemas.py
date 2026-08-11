from pydantic import BaseModel, ConfigDict, Field


class FavoriteRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_type: str = Field(pattern="^(kana|radical|kanji|word)$")
    item_id: str = Field(min_length=1, max_length=64)
    created_at: int
    updated_at: int
    deleted_at: int | None = None


class SettingRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=128)
    value: str
    updated_at: int


class PushRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str = Field(min_length=1, max_length=64)
    favorites: list[FavoriteRow] = []
    settings: list[SettingRow] = []


class PushResponse(BaseModel):
    accepted: dict[str, list[list[str]]]
    server_seq_high: int