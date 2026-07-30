"""Administrative CLI for laboratory accounts and authentication retention."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from .database import SessionFactory
from .db_models import EmailLoginChallenge, UserRecord, UserSessionRecord
from .auth import normalize_email


def list_users(session: Session) -> list[dict[str, str]]:
    users = session.scalars(select(UserRecord).order_by(UserRecord.email))
    return [
        {
            "id": str(user.id),
            "email": user.email,
            "status": user.status,
            "created_at": user.created_at.isoformat(),
            "last_login_at": user.last_login_at.isoformat(),
        }
        for user in users
    ]


def set_user_status(
    session: Session,
    *,
    email: str,
    status: str,
    now: datetime | None = None,
) -> UserRecord:
    normalized = normalize_email(email)
    if normalized is None:
        raise ValueError("A valid complete email address is required.")
    user = session.scalar(
        select(UserRecord)
        .where(UserRecord.email == normalized)
        .with_for_update()
    )
    if user is None:
        raise LookupError(f"No account exists for {normalized}.")
    timestamp = now or datetime.now(timezone.utc)
    user.status = status
    user.updated_at = timestamp
    if status == "disabled":
        session.execute(
            update(UserSessionRecord)
            .where(
                UserSessionRecord.user_id == user.id,
                UserSessionRecord.revoked_at.is_(None),
            )
            .values(revoked_at=timestamp)
        )
    return user


def revoke_user_sessions(
    session: Session,
    *,
    email: str,
    now: datetime | None = None,
) -> int:
    normalized = normalize_email(email)
    if normalized is None:
        raise ValueError("A valid complete email address is required.")
    user_id = session.scalar(
        select(UserRecord.id).where(UserRecord.email == normalized)
    )
    if user_id is None:
        raise LookupError(f"No account exists for {normalized}.")
    result = session.execute(
        update(UserSessionRecord)
        .where(
            UserSessionRecord.user_id == user_id,
            UserSessionRecord.revoked_at.is_(None),
        )
        .values(revoked_at=now or datetime.now(timezone.utc))
    )
    return int(result.rowcount or 0)


def cleanup_auth_records(
    session: Session,
    *,
    now: datetime | None = None,
    challenge_retention: timedelta = timedelta(days=1),
    session_retention: timedelta = timedelta(days=30),
) -> tuple[int, int]:
    timestamp = now or datetime.now(timezone.utc)
    challenge_result = session.execute(
        delete(EmailLoginChallenge).where(
            EmailLoginChallenge.expires_at
            < timestamp - challenge_retention
        )
    )
    session_result = session.execute(
        delete(UserSessionRecord).where(
            or_(
                UserSessionRecord.expires_at
                < timestamp - session_retention,
                UserSessionRecord.revoked_at
                < timestamp - session_retention,
            )
        )
    )
    return (
        int(challenge_result.rowcount or 0),
        int(session_result.rowcount or 0),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage BibMgR users and authentication records."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    list_parser = commands.add_parser("users", help="List accounts.")
    list_parser.add_argument("--json", action="store_true")

    for command in ("enable", "disable", "revoke-sessions"):
        command_parser = commands.add_parser(command)
        command_parser.add_argument("email")

    cleanup_parser = commands.add_parser(
        "cleanup-auth", help="Remove expired authentication records."
    )
    cleanup_parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args()

    try:
        with SessionFactory() as session:
            if arguments.command == "users":
                users = list_users(session)
                if arguments.json:
                    print(json.dumps(users, indent=2))
                else:
                    for user in users:
                        print(
                            f"{user['status']:<8} {user['email']} "
                            f"(last login {user['last_login_at']})"
                        )
                return

            if arguments.command in {"enable", "disable"}:
                user = set_user_status(
                    session,
                    email=arguments.email,
                    status=(
                        "active"
                        if arguments.command == "enable"
                        else "disabled"
                    ),
                )
                session.commit()
                print(f"{user.email}: {user.status}")
                return

            if arguments.command == "revoke-sessions":
                count = revoke_user_sessions(
                    session, email=arguments.email
                )
                session.commit()
                print(f"Revoked {count} session(s).")
                return

            counts = cleanup_auth_records(session)
            if arguments.dry_run:
                session.rollback()
            else:
                session.commit()
            prefix = "Would remove" if arguments.dry_run else "Removed"
            print(
                f"{prefix} {counts[0]} login challenge(s) and "
                f"{counts[1]} session(s)."
            )
    except (LookupError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":  # pragma: no cover
    main()
