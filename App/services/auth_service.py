"""
Authentication service.
"""

import boto3
from botocore.exceptions import ClientError
from datetime import datetime, timedelta
import uuid
from typing import Optional, Dict, Any

from ..core.config import settings
from ..core.security import verify_password, get_password_hash, create_access_token
from ..core.exceptions import (
    InvalidCredentialsError,
    DatabaseError,
    UserAlreadyExistsError
)


class AuthService:
    """Handle user authentication."""
    
    def __init__(self):
        self.dynamodb = boto3.resource(
            'dynamodb',
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key
        )
        self.users_table = self.dynamodb.Table(settings.users_table)
    
    def register_user(self, email: str, password: str, full_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Register a new user.
        
        Args:
            email: User email
            password: Plain text password
            full_name: Optional full name
            
        Returns:
            User data and access token
            
        Raises:
            UserAlreadyExistsError: If email already registered
        """
        # Check if user exists
        if self.get_user_by_email(email):
            raise UserAlreadyExistsError(email)
        
        # Create user
        user_id = str(uuid.uuid4())
        hashed_password = get_password_hash(password)
        current_time = datetime.utcnow().isoformat()
        
        user_data = {
            "user_id": user_id,
            "email": email,
            "hashed_password": hashed_password,
            "full_name": full_name,
            "created_at": current_time,
            "updated_at": current_time
        }
        
        try:
            self.users_table.put_item(Item=user_data)
        except ClientError as e:
            raise DatabaseError(f"Failed to create user: {str(e)}", e)
        
        # Generate token
        access_token = create_access_token(
            data={"sub": user_id, "email": email},
            expires_delta=timedelta(minutes=settings.access_token_expire_minutes)
        )
        
        return {
            "user": {
                "user_id": user_id,
                "email": email,
                "full_name": full_name,
                "created_at": current_time
            },
            "access_token": access_token
        }
    
    def login_user(self, email: str, password: str) -> Dict[str, Any]:
        """
        Login user with email/password.
        
        Args:
            email: User email
            password: Plain text password
            
        Returns:
            User data and access token
            
        Raises:
            InvalidCredentialsError: If credentials are wrong
        """
        # Get user
        user = self.get_user_by_email(email)
        if not user:
            raise InvalidCredentialsError()
        
        # Verify password
        if not verify_password(password, user.get("hashed_password", "")):
            raise InvalidCredentialsError()
        
        # Generate token
        access_token = create_access_token(
            data={"sub": user["user_id"], "email": email},
            expires_delta=timedelta(minutes=settings.access_token_expire_minutes)
        )
        
        return {
            "user": {
                "user_id": user["user_id"],
                "email": user["email"],
                "full_name": user.get("full_name"),
                "created_at": user.get("created_at")
            },
            "access_token": access_token
        }
    
    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get user by email."""
        try:
            response = self.users_table.scan(
                FilterExpression="email = :email",
                ExpressionAttributeValues={":email": email}
            )
            items = response.get("Items", [])
            return items[0] if items else None
        except ClientError:
            return None
    
    def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user by user_id."""
        try:
            response = self.users_table.get_item(Key={"user_id": user_id})
            return response.get("Item")
        except ClientError:
            return None