import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Identity(Base):
    __tablename__ = "identities"
    __table_args__ = (UniqueConstraint("provider", "provider_sub"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(16))
    provider_sub: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    replaced_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("refresh_tokens.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

class UserSyncState(Base):
    __tablename__ = "user_sync_state"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    seq_high: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default="0"
    )


class SyncedMixin:
    """Columns every synced table carries. See docs/SYNC_PROTOCOL.md §2."""

    @declared_attr
    def user_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(
            ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        )

    updated_at: Mapped[int] = mapped_column(BigInteger)
    server_seq: Mapped[int] = mapped_column(BigInteger)
    server_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_device_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

class Favorite(SyncedMixin, Base):
    __tablename__ = "favorites"
    __table_args__ = (Index("ix_favorites_pull", "user_id", "server_seq"),)

    item_type: Mapped[str] = mapped_column(String(16), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[int] = mapped_column(BigInteger)
    deleted_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class Setting(SyncedMixin, Base):
    __tablename__ = "settings"
    __table_args__ = (Index("ix_settings_pull", "user_id", "server_seq"),)

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text)

class StudySet(SyncedMixin, Base):
    __tablename__ = "study_sets"
    __table_args__ = (Index("ix_study_sets_pull", "user_id", "server_seq"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    word_count: Mapped[int] = mapped_column(BigInteger)
    position: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger)
    deleted_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class StudySetWord(SyncedMixin, Base):
    __tablename__ = "study_set_words"
    __table_args__ = (
        Index("ix_study_set_words_pull", "user_id", "server_seq"),
    )

    set_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    word_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    position: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[int] = mapped_column(BigInteger)
    deleted_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class SrsItem(SyncedMixin, Base):
    __tablename__ = "srs_item"
    __table_args__ = (Index("ix_srs_item_pull", "user_id", "server_seq"),)

    category: Mapped[str] = mapped_column(String(16), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    card_type: Mapped[str] = mapped_column(String(32), primary_key=True)
    stability: Mapped[float] = mapped_column(Float)
    difficulty: Mapped[float] = mapped_column(Float)
    due_at: Mapped[int] = mapped_column(BigInteger)
    last_reviewed_at: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    state: Mapped[str] = mapped_column(String(16))
    reps: Mapped[int] = mapped_column(BigInteger)
    lapses: Mapped[int] = mapped_column(BigInteger)
    reps_since_lapse: Mapped[int] = mapped_column(BigInteger)
    displayed_mastery: Mapped[float] = mapped_column(Float)
    has_attempted_guided_writing: Mapped[int] = mapped_column(BigInteger)
    has_attempted_unguided_writing: Mapped[int] = mapped_column(BigInteger)
    is_leech: Mapped[int] = mapped_column(BigInteger)
    introduced_at: Mapped[int] = mapped_column(BigInteger)


class SrsBlacklist(SyncedMixin, Base):
    __tablename__ = "srs_blacklist"
    __table_args__ = (
        Index("ix_srs_blacklist_pull", "user_id", "server_seq"),
    )

    category: Mapped[str] = mapped_column(String(16), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[int] = mapped_column(BigInteger)
    deleted_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class SrsReviewLog(SyncedMixin, Base):
    __tablename__ = "srs_review_log"
    __table_args__ = (
        Index("ix_srs_review_log_pull", "user_id", "server_seq"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    category: Mapped[str] = mapped_column(String(16))
    item_id: Mapped[str] = mapped_column(String(64))
    card_type: Mapped[str] = mapped_column(String(32))
    question_kind: Mapped[str] = mapped_column(String(64))
    grade: Mapped[str] = mapped_column(String(16))
    was_correct: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reviewed_at: Mapped[int] = mapped_column(BigInteger)
    elapsed_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    was_forced_ahead: Mapped[int] = mapped_column(BigInteger)
    prev_stability: Mapped[float] = mapped_column(Float)
    prev_difficulty: Mapped[float] = mapped_column(Float)
    prev_due_at: Mapped[int] = mapped_column(BigInteger)
    prev_state: Mapped[str] = mapped_column(String(16))
    prev_reps: Mapped[int] = mapped_column(BigInteger)
    prev_lapses: Mapped[int] = mapped_column(BigInteger)
    prev_reps_since_lapse: Mapped[int] = mapped_column(BigInteger)
    prev_displayed_mastery: Mapped[float] = mapped_column(Float)
    is_undone: Mapped[int] = mapped_column(BigInteger)