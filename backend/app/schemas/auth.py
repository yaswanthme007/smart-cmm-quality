import uuid

from pydantic import BaseModel, ConfigDict

from app.models.enums import Role


class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    role: Role
    department_id: uuid.UUID | None = None


class DemoUser(BaseModel):
    email: str
    full_name: str
    role: Role
