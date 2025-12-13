"""
FastAPI dependencies for authentication.
"""

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Dict, Optional

from App.core.config import settings
from App.core.security import decode_token
from App.core.exceptions import AuthenticationError
from App.services.auth_service import AuthService

security = HTTPBearer(auto_error=False)
auth_service = AuthService()


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, str]:
    """
    Get current authenticated user from cookies 
    
    Usage:
        @app.get("/protected")
        async def protected_route(current_user: dict = Depends(get_current_user)):
            user_id = current_user["user_id"]
            email = current_user["email"]
    """
    try:
        token: Optional[str] = None
        token = request.cookies.get(settings.access_cookie_name)

        #Temporary fallback to Bearer token (keep for now; remove later)
        if not token and credentials:
            token = credentials.credentials

        if not token:
            raise AuthenticationError("Missing authentication token")
        
        payload = decode_token(token)
        
        user_id = payload.get("sub")
        if not user_id:
            raise AuthenticationError("Invalid token payload")
        
        # Get user from database
        user = auth_service.get_user_by_id(user_id)
        if not user:
            raise AuthenticationError("User not found")
        
        return {
            "user_id": user["user_id"],
            "email": user["email"],
            "full_name": user.get("full_name")
        }
        
    except AuthenticationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"}
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"}
        )