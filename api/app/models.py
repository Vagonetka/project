from pydantic import BaseModel, EmailStr, Field


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr


class User(BaseModel):
    id: int
    name: str
    email: str
    created_at: str | None = None


class OrderCreate(BaseModel):
    user_id: int = Field(gt=0)
    amount: float = Field(gt=0)


class Order(BaseModel):
    id: int
    user_id: int
    amount: float
    status: str
    created_at: str | None = None


class HealthResponse(BaseModel):
    status: str
    version: str