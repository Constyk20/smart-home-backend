from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from fastapi import HTTPException, status

from app.core.security import hash_password, verify_password, create_access_token
from app.db.mongodb import get_database
from app.models.user import UserCreate, UserResponse


async def create_user(user_data: UserCreate) -> UserResponse:
    db = get_database()
    users = db["users"]

    existing = await users.find_one({"email": user_data.email.lower()})
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    user_doc = {
        "email": user_data.email.lower(),
        "hashed_password": hash_password(user_data.password),
        "full_name": user_data.full_name,
        "is_active": True,
        "created_at": datetime.now(timezone.utc),
    }

    result = await users.insert_one(user_doc)
    created = await users.find_one({"_id": result.inserted_id})

    return UserResponse(
        id=str(created["_id"]),
        email=created["email"],
        full_name=created["full_name"],
        created_at=created["created_at"],
        is_active=created["is_active"],
    )


async def authenticate_user(email: str, password: str) -> Optional[dict]:
    db = get_database()
    user = await db["users"].find_one({"email": email.lower()})
    if not user:
        return None
    if not verify_password(password, user["hashed_password"]):
        return None
    return user


async def get_user_by_id(user_id: str) -> Optional[dict]:
    db = get_database()
    try:
        return await db["users"].find_one({"_id": ObjectId(user_id)})
    except Exception:
        return None
