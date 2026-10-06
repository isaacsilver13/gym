from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.auth import (
    clear_session_cookie,
    get_current_user,
    hash_password,
    issue_session_cookie,
    verify_password,
)
from app.db import get_db
from app.models import User
from app.rate_limit import RateLimiter, client_ip, enforce
from app.schemas import UserCredentials, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

login_ip_limiter = RateLimiter(limit=10, window_seconds=300)
login_user_limiter = RateLimiter(limit=5, window_seconds=300)
register_limiter = RateLimiter(limit=5, window_seconds=3600)


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(
    payload: UserCredentials, request: Request, response: Response, db: Session = Depends(get_db)
):
    enforce(register_limiter, client_ip(request))
    existing = db.query(User).filter(User.username == payload.username).one_or_none()
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Username already taken")
    user = User(username=payload.username, password_hash=hash_password(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    issue_session_cookie(response, user.id)
    return user


@router.post("/login", response_model=UserOut)
def login(
    payload: UserCredentials, request: Request, response: Response, db: Session = Depends(get_db)
):
    enforce(login_ip_limiter, client_ip(request))
    enforce(login_user_limiter, payload.username.strip().lower())
    invalid = HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    user = db.query(User).filter(User.username == payload.username).one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise invalid
    issue_session_cookie(response, user.id)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response):
    clear_session_cookie(response)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
