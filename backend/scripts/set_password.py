"""Local operator password reset; secrets are prompted, never command-line arguments."""
import argparse
from getpass import getpass
from sqlalchemy import select
from app.audit import audit
from app.database import SessionLocal
from app.models import User
from app.schemas import Registration
from app.security import hash_password


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    args = parser.parse_args()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == args.email.lower()))
        if user is None:
            parser.error("User not found. Create it with scripts.seed_user first.")
        password = getpass("New password (12+ characters): ")
        if password != getpass("Confirm password: "):
            parser.error("Passwords did not match.")
        try:
            Registration(name=user.name, email=user.email, password=password)
        except ValueError:
            parser.error("Use at least 12 characters and at most 72 UTF-8 bytes.")
        user.password_hash = hash_password(password)
        user.token_version += 1
        audit(db, "user.password.changed", None, "user", user.id, {"source": "local_cli"})
        db.commit()
    print("Password updated. Existing access tokens for this user are invalidated.")


if __name__ == "__main__":
    main()
