import os
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Optional
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
import jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from supabase import Client, create_client

load_dotenv()

# Secret key used to sign JWT tokens. Keep this in environment configuration only.
SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("JWT_SECRET_KEY must be configured")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

# Password hashing setup
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@lru_cache
def get_supabase_client() -> Client:
    """Return the shared client used to query the application users table."""
    load_dotenv()
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")
    if not supabase_url or not supabase_key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be configured")
    return create_client(supabase_url, supabase_key)


# --- Pydantic Models ---
class Token(BaseModel):
    access_token: str
    token_type: str


class UserResponse(BaseModel):
    username: str
    full_name: Optional[str] = None


# --- Helper Functions ---
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password):
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def get_user_record(username: str) -> Optional[dict]:
    """Fetch a single user record from Supabase by its unique username."""
    response = (
        get_supabase_client()
        .table("users")
        .select("username, hashed_password, full_name")
        .eq("username", username)
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


def get_user(username: str) -> Optional[UserResponse]:
    user_record = get_user_record(username)
    if user_record is None:
        return None
    return UserResponse(
        username=user_record["username"],
        full_name=user_record.get("full_name"),
    )


# Dependency to get current authenticated user
async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception

    try:
        user = get_user(username=username)
    except Exception:
        raise credentials_exception
    if user is None:
        raise credentials_exception
    return user


# --- Endpoints ---
@router.post("/login", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    """
    OAuth2 compatible token login, gets an access token for future requests.
    Note: OAuth2PasswordRequestForm uses 'username' and 'password' form fields.
    """
    try:
        user_record = get_user_record(form_data.username)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is unavailable",
        ) from exc

    if not user_record or not verify_password(form_data.password, user_record["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user_record["username"]}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/me", response_model=UserResponse)
async def read_users_me(current_user: UserResponse = Depends(get_current_user)):
    """
    Protected user verification route. Returns the currently authenticated user details.
    """
    return current_user
