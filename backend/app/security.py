from datetime import timedelta
from uuid import UUID
import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from .config import settings
from .database import get_db
from .models import User, now

bearer = HTTPBearer(auto_error=False)
DUMMY_HASH = bcrypt.hashpw(b"timing-only-not-a-user-password", bcrypt.gensalt())


def hash_password(password):
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password, hashed):
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False


def access_token(user):
    issued = now()
    return jwt.encode({"sub": user.id, "exp": issued + timedelta(minutes=settings.access_token_expire_minutes),
                       "iat": issued, "nbf": issued, "iss": "packsure-api", "aud": "packsure-web",
                       "ver": user.token_version}, settings.jwt_secret_key.get_secret_value(), algorithm=settings.jwt_algorithm)


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db=Depends(get_db)):
    unauthorized = HTTPException(401, "Please log in with a valid account.", headers={"WWW-Authenticate": "Bearer"})
    if credentials is None:
        raise unauthorized
    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret_key.get_secret_value(),
                             algorithms=[settings.jwt_algorithm], issuer="packsure-api", audience="packsure-web",
                             options={"require": ["sub", "exp", "iat", "nbf", "ver"]})
        user_id = str(UUID(payload["sub"]))
    except (jwt.InvalidTokenError, ValueError, TypeError):
        raise unauthorized from None
    user = db.get(User, user_id)
    if user is None or not user.is_active or payload["ver"] != user.token_version:
        raise unauthorized
    return user


def admin_user(user=Depends(current_user)):
    if user.role != "admin":
        raise HTTPException(403, "Administrator access required.")
    return user


def user_data(user):
    return {"id": user.id, "name": user.name, "email": user.email, "role": user.role,
            "is_active": user.is_active, "created_at": user.created_at}
