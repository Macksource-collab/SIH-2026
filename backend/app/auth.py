from collections import defaultdict, deque
from threading import Lock
import time
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from .audit import audit
from .database import get_db
from .models import User
from .schemas import Login, Registration
from .security import DUMMY_HASH, access_token, current_user, hash_password, user_data, verify_password
from .config import settings

router = APIRouter(prefix="/auth", tags=["Authentication"])
_login_attempts = defaultdict(deque)
_login_lock = Lock()


def login_key(request, email):
    address = request.client.host if request.client else "unknown"
    return address, str(email).lower()


def enforce_login_limit(key):
    cutoff = time.monotonic() - settings.login_rate_limit_window_seconds
    with _login_lock:
        attempts = _login_attempts[key]
        while attempts and attempts[0] < cutoff:
            attempts.popleft()
        if len(attempts) >= settings.login_rate_limit_attempts:
            raise HTTPException(429, "Too many login attempts. Try again later.",
                                headers={"Retry-After": str(settings.login_rate_limit_window_seconds)})


def failed_login(key):
    with _login_lock:
        _login_attempts[key].append(time.monotonic())


def successful_login(key):
    with _login_lock:
        _login_attempts.pop(key, None)


@router.post("/register", status_code=201)
def register(data: Registration, db=Depends(get_db)):
    user = User(name=data.name, email=data.email, password_hash=hash_password(data.password), role="inspector")
    try:
        db.add(user)
        db.flush()
        audit(db, "user.created", user.id, "user", user.id, {"role": "inspector"})
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An account with this email already exists.") from None
    return user_data(user)


@router.post("/login")
def login(data: Login, request: Request, db=Depends(get_db)):
    key = login_key(request, data.email)
    enforce_login_limit(key)
    user = db.scalar(select(User).where(User.email == str(data.email).lower()))
    valid = verify_password(data.password, user.password_hash if user else DUMMY_HASH.decode("ascii"))
    if not user or not valid or not user.is_active:
        failed_login(key)
        audit(db, "login.failed", user.id if user else None, "user", user.id if user else None,
              {"reason": "invalid_credentials_or_inactive"})
        db.commit()
        raise HTTPException(401, "Invalid email or password.", headers={"WWW-Authenticate": "Bearer"})
    successful_login(key)
    audit(db, "login.succeeded", user.id, "user", user.id)
    db.commit()
    return {"access_token": access_token(user), "token_type": "bearer", "user": user_data(user)}


@router.get("/me")
def me(user=Depends(current_user)):
    return user_data(user)
