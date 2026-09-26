"""Create a user without putting a password in command-line arguments or source."""
import argparse
from getpass import getpass
import os
from sqlalchemy import select
from app.audit import audit
from app.database import SessionLocal
from app.models import User
from app.schemas import Registration
from app.security import hash_password


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--role", choices=["admin", "inspector"], required=True)
    parser.add_argument("--password-env", help="Read password from this environment variable instead of prompting")
    args = parser.parse_args()
    password = os.environ.get(args.password_env, "") if args.password_env else getpass("Password (12+ characters): ")
    try:
        data = Registration(name=args.name, email=args.email, password=password)
    except ValueError:
        parser.error("Use a valid email, nonblank name, and password of 12+ characters and at most 72 UTF-8 bytes.")
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == data.email)):
            parser.error("That email already exists; existing users are never overwritten by this script.")
        user = User(name=data.name, email=data.email, role=args.role, password_hash=hash_password(data.password))
        db.add(user)
        db.flush()
        audit(db, "user.created", None, "user", user.id, {"role": args.role, "source": "seed_cli"})
        db.commit()
    print(f"Created {args.role} account: {data.email}")


if __name__ == "__main__":
    main()
