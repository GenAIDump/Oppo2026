# File: Oppo/a2a_host/auth.py
# Purpose: Authentication logic (JWT, Internal API Key dependencies)

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, APIKeyHeader
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

# Import config relative to this file's location within the package
from .config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES, INTERNAL_SERVICE_API_KEY

logger = logging.getLogger(__name__)

# --- User Model and Mock DB ---
# Replace this with your actual user storage (e.g., database lookup via MCP?)
class User(BaseModel):
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    disabled: Optional[bool] = None

class UserInDB(User):
    hashed_password: str

# --- Password Hashing ---
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password, hashed_password):
    """Verifies a plain password against a hashed password."""
    if not plain_password or not hashed_password:
        return False
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception as e:
        logger.error(f"Error verifying password: {e}")
        return False

def get_password_hash(password):
    """Generates a bcrypt hash for a password."""
    return pwd_context.hash(password)

# Mock user database (Replace with real database interaction)
# Password for "testuser" is "password"
# Generate hash using: print(get_password_hash("password"))
FAKE_USERS_DB = {
    "testuser": {
        "username": "testuser",
        "full_name": "Test User",
        "email": "test@example.com",
        "hashed_password": "$2b$12$EixZaYVK1.L.zQ8aF4zCe.bpKEg5f5g5r0z.J8q9z.J5rL5v3n2W.", # Hash for "password"
        "disabled": False,
    }
    # Add more users as needed, potentially loading from config or DB at startup
}

# --- User Lookup ---
def get_user(username: str) -> Optional[UserInDB]:
    """Retrieves user details from the mock DB."""
    if username in FAKE_USERS_DB:
        user_dict = FAKE_USERS_DB[username]
        return UserInDB(**user_dict)
    logger.warning(f"User '{username}' not found in FAKE_USERS_DB.")
    return None

# --- Authentication Logic ---
def authenticate_user(username: str, password: str) -> Optional[UserInDB]:
    """Authenticates a user based on username and password."""
    user = get_user(username)
    if not user or user.disabled:
        logger.warning(f"Authentication failed for user '{username}': User not found or disabled.")
        return None
    if not verify_password(password, user.hashed_password):
        logger.warning(f"Authentication failed for user '{username}': Invalid password.")
        return None
    logger.info(f"User '{username}' authenticated successfully.")
    return user

# --- Token Creation ---
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Creates a JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    if not SECRET_KEY:
        logger.critical("Cannot create access token: SECRET_KEY is not configured.")
        raise ValueError("SECRET_KEY is not set, cannot create tokens.")
    try:
        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        return encoded_jwt
    except Exception as e:
        logger.critical(f"Error encoding JWT token: {e}", exc_info=True)
        raise ValueError("Could not encode token") from e


# --- FastAPI Dependencies ---

# OAuth2 Scheme for standard user login
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token") # Matches endpoint in server.py

async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    """Dependency to get the current user from JWT token."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not SECRET_KEY:
        logger.error("Cannot validate token: SECRET_KEY is not configured.")
        raise credentials_exception

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: Optional[str] = payload.get("sub")
        if username is None:
            logger.warning("Token validation failed: No 'sub' (username) in payload.")
            raise credentials_exception
        # Check expiration (decode should raise JWTError if expired)
        # Optionally add token scope validation here if needed
    except JWTError as e:
         logger.warning(f"JWT Error during token validation: {e}", exc_info=False)
         raise credentials_exception
    except Exception as e:
        logger.error(f"Unexpected error during token validation: {e}", exc_info=True)
        raise credentials_exception

    user_in_db = get_user(username)
    if user_in_db is None:
        logger.warning(f"Token validation failed: User '{username}' from token not found.")
        raise credentials_exception
    # Return the basic User model, not UserInDB with hash
    # Use exclude to prevent accidentally leaking hash if UserInDB was returned directly
    return User(**user_in_db.model_dump(exclude={'hashed_password'}))

async def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    """Dependency to ensure the current user is active."""
    if current_user.disabled:
        logger.warning(f"Access denied for disabled user: {current_user.username}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user")
    return current_user

# --- API Key Auth for Internal Services ---
API_KEY_NAME = "X-API-KEY" # Header name for the internal API key
api_key_header_auth = APIKeyHeader(name=API_KEY_NAME, auto_error=True) # auto_error=True raises 403 if missing/invalid

async def verify_internal_api_key(api_key: str = Depends(api_key_header_auth)):
    """Dependency to verify the internal service API key."""
    # Check if the key is configured and matches
    if not INTERNAL_SERVICE_API_KEY:
         logger.error("Internal API Key verification failed: INTERNAL_SERVICE_API_KEY not configured on server.")
         # Return 500 because it's a server config issue
         raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal API Key not configured")

    if api_key != INTERNAL_SERVICE_API_KEY:
        logger.warning("Internal API Key verification failed: Invalid key provided.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, # Use 403 for invalid key
            detail="Invalid or missing Internal Service API Key",
        )
    # Key is valid
    logger.debug("Internal API Key verified successfully.")
    return api_key # Return the key if needed, otherwise just let it pass