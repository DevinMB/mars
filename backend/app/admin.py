"""Command-line administration for a running MARS install.

Exists because the first administrator's password is printed once to the log, and
"I wasn't watching the log" is not a reason to lose an installation. Everything
here operates directly on the database, so it works even when nobody can sign in.

    docker compose exec console python -m app.admin list-users
    docker compose exec console python -m app.admin reset-password admin
    docker compose exec console python -m app.admin create-user operator --role admin
"""
from __future__ import annotations

import argparse
import secrets as pysecrets
import sys

from sqlalchemy import select

from .auth import hash_password, issue_api_token
from .db import Base, engine, session_scope
from .models import ApiToken, Role, User


def _print_credentials(username: str, password: str) -> None:
    line = "=" * 58
    print(f"\n  {line}")
    print(f"   username: {username}")
    print(f"   password: {password}")
    print("   Shown once. Store it somewhere before closing this window.")
    print(f"  {line}\n")


def cmd_list_users(_: argparse.Namespace) -> int:
    with session_scope() as db:
        users = db.scalars(select(User).order_by(User.username)).all()
        if not users:
            print("No users exist. Start the console once to create the first admin,")
            print("or run: python -m app.admin create-user <name> --role admin")
            return 0
        print(f"{'USERNAME':<24} {'ROLE':<8} {'STATE':<10} LAST SIGN-IN")
        for u in users:
            state = "disabled" if u.disabled else ("must-change" if u.must_change_password else "ok")
            last = u.last_login_at.strftime("%Y-%m-%d %H:%M") if u.last_login_at else "never"
            print(f"{u.username:<24} {u.role:<8} {state:<10} {last}")
    return 0


def cmd_reset_password(args: argparse.Namespace) -> int:
    with session_scope() as db:
        user = db.scalar(select(User).where(User.username == args.username))
        if user is None:
            print(f"No user named '{args.username}'.", file=sys.stderr)
            return 1

        password = args.password or pysecrets.token_urlsafe(18)
        user.password_hash = hash_password(password)
        # A generated password should be replaced; one the operator chose should not nag.
        user.must_change_password = args.password is None
        user.disabled = False

        # Changing the hash invalidates every outstanding session cookie for this
        # user, which is the behaviour you want from a password reset.
        print(f"Password reset for '{user.username}'. Existing sessions are now invalid.")
        if args.password is None:
            _print_credentials(user.username, password)
    return 0


def cmd_create_user(args: argparse.Namespace) -> int:
    with session_scope() as db:
        if db.scalar(select(User).where(User.username == args.username)):
            print(f"A user named '{args.username}' already exists.", file=sys.stderr)
            return 1

        password = args.password or pysecrets.token_urlsafe(18)
        db.add(
            User(
                username=args.username,
                password_hash=hash_password(password),
                role=args.role,
                must_change_password=args.password is None,
            )
        )
        print(f"Created '{args.username}' with role {args.role}.")
        if args.password is None:
            _print_credentials(args.username, password)
    return 0


def cmd_disable_user(args: argparse.Namespace) -> int:
    with session_scope() as db:
        user = db.scalar(select(User).where(User.username == args.username))
        if user is None:
            print(f"No user named '{args.username}'.", file=sys.stderr)
            return 1
        admins = db.scalars(
            select(User).where(User.role == Role.ADMIN.value, User.disabled.is_(False))
        ).all()
        if user.role == Role.ADMIN.value and len(admins) <= 1:
            print("Refusing to disable the only administrator.", file=sys.stderr)
            return 1
        user.disabled = args.disable
        print(f"{'Disabled' if args.disable else 'Enabled'} '{user.username}'.")
    return 0


def cmd_issue_token(args: argparse.Namespace) -> int:
    with session_scope() as db:
        user = db.scalar(select(User).where(User.username == args.username))
        if user is None:
            print(f"No user named '{args.username}'.", file=sys.stderr)
            return 1
        _, plaintext = issue_api_token(db, user, args.name)
        print(f"\nAPI token '{args.name}' for {user.username}:\n")
        print(f"  {plaintext}\n")
        print("  Shown once. Send it as: Authorization: Bearer <token>\n")
    return 0


def cmd_revoke_token(args: argparse.Namespace) -> int:
    with session_scope() as db:
        tokens = db.scalars(select(ApiToken).where(ApiToken.name == args.name)).all()
        if not tokens:
            print(f"No token named '{args.name}'.", file=sys.stderr)
            return 1
        for t in tokens:
            db.delete(t)
        print(f"Revoked {len(tokens)} token(s) named '{args.name}'.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.admin",
        description="Administer a MARS installation from the command line.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list-users", help="List accounts").set_defaults(func=cmd_list_users)

    p = sub.add_parser("reset-password", help="Reset a password, generating one if not given")
    p.add_argument("username")
    p.add_argument("--password", help="Set this password instead of generating one")
    p.set_defaults(func=cmd_reset_password)

    p = sub.add_parser("create-user", help="Create an account")
    p.add_argument("username")
    p.add_argument("--role", choices=[r.value for r in Role], default=Role.EDITOR.value)
    p.add_argument("--password", help="Set this password instead of generating one")
    p.set_defaults(func=cmd_create_user)

    p = sub.add_parser("disable-user", help="Disable an account")
    p.add_argument("username")
    p.set_defaults(func=cmd_disable_user, disable=True)

    p = sub.add_parser("enable-user", help="Re-enable an account")
    p.add_argument("username")
    p.set_defaults(func=cmd_disable_user, disable=False)

    p = sub.add_parser("issue-token", help="Create an API token")
    p.add_argument("username")
    p.add_argument("--name", required=True, help="What this token is for")
    p.set_defaults(func=cmd_issue_token)

    p = sub.add_parser("revoke-token", help="Revoke API tokens by name")
    p.add_argument("--name", required=True)
    p.set_defaults(func=cmd_revoke_token)

    args = parser.parse_args(argv)
    # Works against a database that has never been started by the app.
    Base.metadata.create_all(engine)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
