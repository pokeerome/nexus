import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from models import Membership, User
from security import ALGORITHM, SECRET_KEY

bearer = HTTPBearer()


def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    try:
        payload = jwt.decode(creds.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("typ") == "mcp":
            raise ValueError("MCP tokens cannot be used to log in")
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user

def require_membership(
    workspace_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Membership:
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == user.id,
            Membership.workspace_id == workspace_id,
        )
    )
    if not membership:
        raise HTTPException(status_code=403, detail="You are not a member of this workspace")
    return membership