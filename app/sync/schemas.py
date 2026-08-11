from typing import Any

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

class StudySetRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    name: str = Field(max_length=255)
    word_count: int
    position: int | None = None
    created_at: int
    updated_at: int
    deleted_at: int | None = None


class StudySetWordRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    set_id: str = Field(min_length=1, max_length=64)
    word_id: int
    position: int
    created_at: int
    updated_at: int
    deleted_at: int | None = None


class SrsItemRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str = Field(pattern="^(kana|kanji|word|radical)$")
    item_id: str = Field(min_length=1, max_length=64)
    card_type: str = Field(max_length=32)
    stability: float
    difficulty: float
    due_at: int
    last_reviewed_at: int | None = None
    state: str = Field(pattern="^(new|learning|review|relearning)$")
    reps: int
    lapses: int
    reps_since_lapse: int
    displayed_mastery: float
    has_attempted_guided_writing: int
    has_attempted_unguided_writing: int
    is_leech: int
    introduced_at: int
    updated_at: int


class SrsBlacklistRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str = Field(pattern="^(kana|kanji|word|radical)$")
    item_id: str = Field(min_length=1, max_length=64)
    created_at: int
    updated_at: int
    deleted_at: int | None = None


class SrsReviewLogRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    session_id: str | None = None
    category: str = Field(max_length=16)
    item_id: str = Field(min_length=1, max_length=64)
    card_type: str = Field(max_length=32)
    question_kind: str = Field(max_length=64)
    grade: str = Field(pattern="^(nothing|something|hard|okay|easy)$")
    was_correct: int | None = None
    reviewed_at: int
    elapsed_ms: int | None = None
    was_forced_ahead: int
    prev_stability: float
    prev_difficulty: float
    prev_due_at: int
    prev_state: str = Field(max_length=16)
    prev_reps: int
    prev_lapses: int
    prev_reps_since_lapse: int
    prev_displayed_mastery: float
    is_undone: int
    updated_at: int


class PushRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str = Field(min_length=1, max_length=64)
    favorites: list[FavoriteRow] = []
    settings: list[SettingRow] = []
    study_sets: list[StudySetRow] = []
    study_set_words: list[StudySetWordRow] = []
    srs_item: list[SrsItemRow] = []
    srs_blacklist: list[SrsBlacklistRow] = []
    srs_review_log: list[SrsReviewLogRow] = []


class PushResponse(BaseModel):
    accepted: dict[str, list[list[str]]]
    highest_reserved_seq: int = Field(
        description=(
            "Diagnostic only. Highest sequence reserved by this push, which "
            "may belong to no row if a row lost LWW. NOT a pull cursor — "
            "the cursor comes only from /sync/pull's next_since."
        )
    )

class PullRow(BaseModel):
    table: str
    server_seq: int
    row: dict[str, Any]


class PullResponse(BaseModel):
    rows: list[PullRow]
    next_since: int
    has_more: bool