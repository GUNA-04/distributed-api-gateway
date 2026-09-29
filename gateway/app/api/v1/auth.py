"""
Authentication routes.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from gateway.app.db.session import get_db
from gateway.app.models.database import User
from gateway.app.core.security import hash_password, verify_password, create_access_token
from gateway.app.schemas.order import UserCreateRequest, TokenResponse
from common.app.logging_config import setup_logger

logger = setup_logger(__name__)
router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(user_req: UserCreateRequest, db: AsyncSession = Depends(get_db)):
    """Register a new user account."""
    existing = await db.execute(
        select(User)
        .where(or_(User.username == user_req.username, User.email == user_req.email))
        .limit(1)
    )
    if existing.scalars().first():
        raise HTTPException(status_code=409, detail="Username or email already exists")

    user = User(
        username=user_req.username,
        email=user_req.email,
        hashed_password=hash_password(user_req.password),
        tier="free",
        is_active=True,
        is_verified=False,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info("New user registered", extra={"user_id": str(user.id), "username": user.username})
    return {"user_id": str(user.id), "username": user.username, "message": "User created"}


@router.post("/login", response_model=TokenResponse)
async def login(
    username: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Authenticate and get JWT token using OAuth2 form fields."""
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is inactive")

    token = create_access_token(data={"sub": str(user.id), "username": user.username, "tier": user.tier})
    logger.info("User logged in", extra={"user_id": str(user.id)})
    return TokenResponse(access_token=token)
