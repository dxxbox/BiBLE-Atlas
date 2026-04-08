from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List, Optional

from pydantic import BaseModel

class Role(str, Enum):
    USER = "user"
    PRO = "premium"
    ADMIN = "admin"
    ROOT = "root"

class Identity(BaseModel):
    role: Role
    user_id: str
    account_id: Optional[str] = None
    email: Optional[str] = None
    avatar: Optional[str] = None