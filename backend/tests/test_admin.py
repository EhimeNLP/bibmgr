from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from bibmgr_backend.admin import (
    cleanup_auth_records,
    revoke_user_sessions,
    set_user_status,
)
from bibmgr_backend.db_models import (
    Base,
    EmailLoginChallenge,
    UserRecord,
    UserSessionRecord,
)


def test_disable_revokes_sessions_and_cleanup_honors_retention() -> None:
    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, class_=Session)
    now = datetime(2026, 7, 28, tzinfo=timezone.utc)

    with sessions.begin() as session:
        user = UserRecord(
            email="member@example.test",
            first_verified_at=now,
            last_login_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(user)
        session.flush()
        session.add_all(
            [
                UserSessionRecord(
                    user_id=user.id,
                    token_digest="a" * 64,
                    created_at=now - timedelta(days=60),
                    expires_at=now - timedelta(days=40),
                ),
                EmailLoginChallenge(
                    email=user.email,
                    code_digest="b" * 64,
                    attempts=0,
                    requested_at=now - timedelta(days=3),
                    expires_at=now - timedelta(days=2),
                ),
            ]
        )

    with sessions.begin() as session:
        disabled = set_user_status(
            session,
            email="member@example.test",
            status="disabled",
            now=now,
        )
        assert disabled.status == "disabled"

    with sessions.begin() as session:
        assert revoke_user_sessions(
            session,
            email="member@example.test",
            now=now,
        ) == 0
        assert cleanup_auth_records(session, now=now) == (1, 1)

    with sessions() as session:
        assert session.scalar(
            select(func.count()).select_from(UserRecord)
        ) == 1
        assert session.scalar(
            select(func.count()).select_from(UserSessionRecord)
        ) == 0
