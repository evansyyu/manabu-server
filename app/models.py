import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    LargeBinary,
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
    # Apple only, and only when revocation is configured: the Apple refresh
    # token obtained by exchanging the sign-in authorizationCode. Held solely
    # so account deletion can revoke it (guideline 5.1.1(v)); it is never used
    # to mint sessions.
    apple_refresh_token: Mapped[str | None] = mapped_column(String(2048), nullable=True)
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

class UserAvatar(Base):
    """The user's chosen profile picture — exactly one per user (PK is the
    user id), stored inline as bytes: images are client-resized to 512×512
    JPEG (tens of KB) and capped at MAX_AVATAR_BYTES in the route, so a bytea
    column beats an object store the deployment doesn't have. `updated_at` is
    the client's ms-epoch clock and the whole conflict rule: last writer wins,
    same convention as the synced tables' LWW. Dies with the user row
    (CASCADE), so account deletion needs no extra step."""

    __tablename__ = "user_avatar"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    content_type: Mapped[str] = mapped_column(String(64))
    data: Mapped[bytes] = mapped_column(LargeBinary)
    updated_at: Mapped[int] = mapped_column(BigInteger)
    server_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
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

class SrsDailyCounter(SyncedMixin, Base):
    __tablename__ = "srs_daily_counter"
    __table_args__ = (
        Index("ix_srs_daily_counter_pull", "user_id", "server_seq"),
    )

    category: Mapped[str] = mapped_column(String(16), primary_key=True)
    day: Mapped[str] = mapped_column(String(10), primary_key=True)
    device_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    new_count: Mapped[int] = mapped_column(BigInteger)
    review_count: Mapped[int] = mapped_column(BigInteger)


class StudyActivity(SyncedMixin, Base):
    __tablename__ = "study_activity"
    __table_args__ = (
        Index("ix_study_activity_pull", "user_id", "server_seq"),
    )

    day: Mapped[str] = mapped_column(String(10), primary_key=True)
    device_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    active_ms: Mapped[int] = mapped_column(BigInteger)
    cards: Mapped[int] = mapped_column(BigInteger)


class SrsItemTombstone(SyncedMixin, Base):
    __tablename__ = "srs_item_tombstone"
    __table_args__ = (
        Index("ix_srs_item_tombstone_pull", "user_id", "server_seq"),
    )

    category: Mapped[str] = mapped_column(String(16), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    card_type: Mapped[str] = mapped_column(String(32), primary_key=True)
    deleted_at: Mapped[int] = mapped_column(BigInteger)

class CrashReport(Base):
    """A client-reported JS crash/error, for post-production troubleshooting.

    Deliberately carries no account linkage — the reporter is anonymous by
    design, matching the server's no-identity posture. `install_id` is a
    random per-install UUID the client generates, enough to answer "one
    device in a loop or many devices affected" without naming anyone.
    `occurred_at` is the client's ms-epoch clock at capture time (reports
    arrive on the *next* launch — a dying process can't reliably POST), and
    `received_at` is ours. Text fields are capped in the route, not here.
    """

    __tablename__ = "crash_reports"
    __table_args__ = (
        Index("ix_crash_reports_received_at", "received_at"),
        Index("ix_crash_reports_install_id", "install_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    install_id: Mapped[str] = mapped_column(String(64))
    platform: Mapped[str] = mapped_column(String(16))
    os_version: Mapped[str] = mapped_column(String(32))
    app_version: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(16))
    is_fatal: Mapped[bool] = mapped_column()
    message: Mapped[str] = mapped_column(Text)
    stack: Mapped[str] = mapped_column(Text)
    occurred_at: Mapped[int] = mapped_column(BigInteger)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
