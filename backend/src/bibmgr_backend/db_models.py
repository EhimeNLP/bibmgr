"""Relational persistence model for registered bibliographic records."""

from __future__ import annotations

from datetime import datetime, timezone
import uuid
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


json_type = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


class UserRecord(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active"
    )
    first_verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    last_login_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'disabled')",
            name="ck_users_status",
        ),
    )


class EmailLoginChallenge(Base):
    __tablename__ = "email_login_challenges"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    code_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    request_ip: Mapped[str | None] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    __table_args__ = (
        CheckConstraint(
            "attempts >= 0",
            name="ck_email_login_challenges_attempts",
        ),
        Index(
            "ix_email_login_challenges_email_requested_at",
            "email",
            "requested_at",
        ),
        Index(
            "ix_email_login_challenges_request_ip_requested_at",
            "request_ip",
            "requested_at",
        ),
    )


class UserSessionRecord(Base):
    __tablename__ = "user_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    token_digest: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    user: Mapped[UserRecord] = relationship(lazy="joined")

    __table_args__ = (
        Index("ix_user_sessions_user_id", "user_id"),
        Index("ix_user_sessions_expires_at", "expires_at"),
    )


class ReferenceRecord(Base):
    __tablename__ = "bibliographic_references"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    citation_key: Mapped[str] = mapped_column(Text, nullable=False)
    entry_type: Mapped[str] = mapped_column(Text, nullable=False)
    work_type: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    publication_year: Mapped[int | None] = mapped_column(SmallInteger)
    publication_date_raw: Mapped[str | None] = mapped_column(Text)
    venue_raw: Mapped[str | None] = mapped_column(Text)
    venue_id: Mapped[str | None] = mapped_column(Text)
    venue_name: Mapped[str | None] = mapped_column(Text)
    # The physical column keeps its original name for migration compatibility;
    # application code treats it as the lossless stored BibTeX representation.
    canonical_bibtex: Mapped[str] = mapped_column(
        "raw_bibtex", Text, nullable=False
    )
    source_revision: Mapped[str] = mapped_column(String(71), nullable=False)
    registration_source: Mapped[str] = mapped_column(
        String(16), nullable=False
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
    )
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
    )
    semantic_data: Mapped[dict[str, Any]] = mapped_column(
        json_type, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    contributors: Mapped[list[ReferenceContributor]] = relationship(
        back_populates="reference",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
        order_by="ReferenceContributor.role, ReferenceContributor.position",
    )
    identifiers: Mapped[list[ReferenceIdentifier]] = relationship(
        back_populates="reference",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
        order_by="ReferenceIdentifier.scheme, ReferenceIdentifier.position",
    )
    urls: Mapped[list[ReferenceUrl]] = relationship(
        back_populates="reference",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
        order_by="ReferenceUrl.position",
    )
    citation_contexts: Mapped[list[CitationContextRecord]] = relationship(
        back_populates="reference",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
        order_by="CitationContextRecord.created_at",
    )

    __table_args__ = (
        CheckConstraint(
            "registration_source IN ('manual', 'file', 'edit')",
            name="ck_bibliographic_references_registration_source",
        ),
        Index(
            "ix_bibliographic_references_citation_key",
            "citation_key",
        ),
        Index(
            "ix_bibliographic_references_publication_year",
            "publication_year",
        ),
        Index(
            "ix_bibliographic_references_updated_at",
            "updated_at",
        ),
        Index(
            "ix_bibliographic_references_created_by_user_id",
            "created_by_user_id",
        ),
        Index(
            "ix_bibliographic_references_updated_by_user_id",
            "updated_by_user_id",
        ),
        Index(
            "ix_bibliographic_references_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ).ddl_if(dialect="postgresql"),
        Index(
            "ix_bibliographic_references_citation_key_trgm",
            "citation_key",
            postgresql_using="gin",
            postgresql_ops={"citation_key": "gin_trgm_ops"},
        ).ddl_if(dialect="postgresql"),
        Index(
            "ix_bibliographic_references_venue_raw_trgm",
            "venue_raw",
            postgresql_using="gin",
            postgresql_ops={"venue_raw": "gin_trgm_ops"},
        ).ddl_if(dialect="postgresql"),
        Index(
            "ix_bibliographic_references_semantic_data",
            "semantic_data",
            postgresql_using="gin",
            postgresql_ops={"semantic_data": "jsonb_path_ops"},
        ).ddl_if(dialect="postgresql"),
    )


class ReferenceContributor(Base):
    __tablename__ = "reference_contributors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reference_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("bibliographic_references.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    given_names: Mapped[list[str]] = mapped_column(json_type, nullable=False)
    family_names: Mapped[list[str]] = mapped_column(json_type, nullable=False)
    name_prefixes: Mapped[list[str]] = mapped_column(json_type, nullable=False)
    name_suffixes: Mapped[list[str]] = mapped_column(json_type, nullable=False)
    literal_name: Mapped[str | None] = mapped_column(Text)
    semantic_data: Mapped[dict[str, Any]] = mapped_column(
        json_type, nullable=False
    )

    reference: Mapped[ReferenceRecord] = relationship(
        back_populates="contributors"
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('author', 'editor')",
            name="ck_reference_contributors_role",
        ),
        UniqueConstraint(
            "reference_id",
            "role",
            "position",
            name="uq_reference_contributors_position",
        ),
        Index(
            "ix_reference_contributors_display_name_trgm",
            "display_name",
            postgresql_using="gin",
            postgresql_ops={"display_name": "gin_trgm_ops"},
        ).ddl_if(dialect="postgresql"),
    )


class ReferenceIdentifier(Base):
    __tablename__ = "reference_identifiers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reference_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("bibliographic_references.id", ondelete="CASCADE"),
        nullable=False,
    )
    scheme: Mapped[str] = mapped_column(String(32), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_value: Mapped[str] = mapped_column(Text, nullable=False)
    semantic_data: Mapped[dict[str, Any]] = mapped_column(
        json_type, nullable=False
    )

    reference: Mapped[ReferenceRecord] = relationship(
        back_populates="identifiers"
    )

    __table_args__ = (
        UniqueConstraint(
            "reference_id",
            "scheme",
            "normalized_value",
            name="uq_reference_identifiers_per_reference",
        ),
        Index(
            "uq_reference_identifiers_strong_identity",
            "scheme",
            "normalized_value",
            unique=True,
            postgresql_where=text("scheme IN ('doi', 'arxiv')"),
            sqlite_where=text("scheme IN ('doi', 'arxiv')"),
        ),
        Index(
            "ix_reference_identifiers_normalized_value",
            "normalized_value",
        ),
        Index(
            "ix_reference_identifiers_value_trgm",
            "normalized_value",
            postgresql_using="gin",
            postgresql_ops={"normalized_value": "gin_trgm_ops"},
        ).ddl_if(dialect="postgresql"),
    )


class ReferenceUrl(Base):
    __tablename__ = "reference_urls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reference_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("bibliographic_references.id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    semantic_data: Mapped[dict[str, Any]] = mapped_column(
        json_type, nullable=False
    )

    reference: Mapped[ReferenceRecord] = relationship(back_populates="urls")

    __table_args__ = (
        UniqueConstraint(
            "reference_id",
            "position",
            name="uq_reference_urls_position",
        ),
    )


class CitationContextRecord(Base):
    __tablename__ = "citation_contexts"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    reference_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("bibliographic_references.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_paper_title: Mapped[str | None] = mapped_column(Text)
    source_file_name: Mapped[str | None] = mapped_column(Text)
    before_text: Mapped[str | None] = mapped_column(Text)
    context_text: Mapped[str] = mapped_column(Text, nullable=False)
    after_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    reference: Mapped[ReferenceRecord] = relationship(
        back_populates="citation_contexts"
    )


class ReferenceHistoryHead(Base):
    __tablename__ = "reference_history_heads"

    reference_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True
    )
    latest_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    __table_args__ = (
        CheckConstraint(
            "latest_revision >= 0",
            name="ck_reference_history_heads_latest_revision",
        ),
        Index(
            "ix_reference_history_heads_updated_at",
            "updated_at",
        ),
    )


class ReferenceAuditEvent(Base):
    __tablename__ = "reference_audit_events"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    reference_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    restored_from_revision: Mapped[int | None] = mapped_column(Integer)
    before_data: Mapped[dict[str, Any] | None] = mapped_column(json_type)
    after_data: Mapped[dict[str, Any] | None] = mapped_column(json_type)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    actor: Mapped[UserRecord] = relationship(lazy="joined")

    __table_args__ = (
        CheckConstraint(
            (
                "action IN "
                "('baseline', 'create', 'update', 'delete', 'restore', 'context')"
            ),
            name="ck_reference_audit_events_action",
        ),
        CheckConstraint(
            "revision >= 1",
            name="ck_reference_audit_events_revision",
        ),
        CheckConstraint(
            "restored_from_revision IS NULL OR restored_from_revision >= 1",
            name="ck_reference_audit_events_restored_from_revision",
        ),
        UniqueConstraint(
            "reference_id",
            "revision",
            name="uq_reference_audit_events_revision",
        ),
        Index(
            "ix_reference_audit_events_reference_occurred_at",
            "reference_id",
            "occurred_at",
        ),
        Index(
            "ix_reference_audit_events_actor_occurred_at",
            "actor_user_id",
            "occurred_at",
        ),
    )
