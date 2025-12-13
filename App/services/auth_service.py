"""
Authentication service.
"""

import boto3
from botocore.exceptions import ClientError
from datetime import datetime, timedelta
import uuid
from typing import Optional, Dict, Any

from App.core.config import settings
from App.core.security import verify_password, get_password_hash, create_access_token
from App.core.exceptions import (
    InvalidCredentialsError,
    DatabaseError,
    UserAlreadyExistsError,
)


class AuthService:
    """Handle user authentication."""

    def __init__(self):
        self.dynamodb = boto3.resource(
            "dynamodb",
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
        )
        self.users_table = self.dynamodb.Table(settings.users_table)

    # -------------------------------------------------------------------------
    # Existing: Local email/password registration
    # -------------------------------------------------------------------------
    def register_user(self, email: str, password: str, full_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Register a new user (local auth).

        Raises:
            UserAlreadyExistsError: If email already registered
        """
        # Check if user exists (any provider)
        if self.get_user_by_email(email):
            raise UserAlreadyExistsError(email)

        user_id = str(uuid.uuid4())
        hashed_password = get_password_hash(password)
        current_time = datetime.utcnow().isoformat()

        user_data = {
            "user_id": user_id,
            "email": email,
            "hashed_password": hashed_password,
            "full_name": full_name,
            "auth_provider": "local",
            "created_at": current_time,
            "updated_at": current_time,
            "last_login_at": current_time,
        }

        try:
            self.users_table.put_item(Item=user_data)
        except ClientError as e:
            raise DatabaseError(f"Failed to create user: {str(e)}", e)

        access_token = create_access_token(
            data={"sub": user_id, "email": email},
            expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
        )

        return {
            "user": {
                "user_id": user_id,
                "email": email,
                "full_name": full_name,
                "created_at": current_time,
            },
            "access_token": access_token,
        }

    # -------------------------------------------------------------------------
    # Existing: Local email/password login
    # -------------------------------------------------------------------------
    def login_user(self, email: str, password: str) -> Dict[str, Any]:
        """
        Login user with email/password (local auth).

        Raises:
            InvalidCredentialsError: If credentials are wrong
        """
        user = self.get_user_by_email(email)
        if not user:
            raise InvalidCredentialsError()

        # If this account is NOT a local/password account, do not allow password login
        if user.get("auth_provider") == "google":
            # Keep it as InvalidCredentialsError if you want to avoid revealing provider,
            # but for your app UX you can choose to raise a more specific error later.
            raise InvalidCredentialsError()

        if not verify_password(password, user.get("hashed_password", "")):
            raise InvalidCredentialsError()

        # Update last_login_at (best-effort)
        self._touch_last_login(user["user_id"])

        access_token = create_access_token(
            data={"sub": user["user_id"], "email": email},
            expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
        )

        return {
            "user": {
                "user_id": user["user_id"],
                "email": user["email"],
                "full_name": user.get("full_name"),
                "created_at": user.get("created_at"),
            },
            "access_token": access_token,
        }

    # -------------------------------------------------------------------------
    # NEW: Google OAuth login or register
    # -------------------------------------------------------------------------
    def login_or_register_google_user(
        self,
        google_sub: str,
        email: str,
        full_name: Optional[str] = None,
        email_verified: bool = False,
    ) -> Dict[str, Any]:
        """
        Login or register a user authenticated via Google (OIDC).

        Policy:
          - If user exists with same email and auth_provider == "local": reject (no auto-merge)
          - If user exists with google_sub: login
          - Else create a new google user

        Returns:
            { "user": {...}, "access_token": "..." }
        """
        # 1) Try to find by google_sub (scan for now; later replace with GSI)
        user = self.get_user_by_google_sub(google_sub)
        if user:
            self._touch_last_login(user["user_id"])
            return self._issue_token_response(user)

        # 2) Collision check: same email already exists?
        existing = self.get_user_by_email(email)
        if existing:
            # If it's a local/password account, DO NOT auto-link.
            if existing.get("auth_provider") == "local":
                raise UserAlreadyExistsError(email)

            # If it's already a google account (but missing sub for some reason),
            # we can attach google_sub defensively.
            if existing.get("auth_provider") == "google" and not existing.get("google_sub"):
                try:
                    self.users_table.update_item(
                        Key={"user_id": existing["user_id"]},
                        UpdateExpression="SET google_sub = :gs, updated_at = :u",
                        ExpressionAttributeValues={
                            ":gs": google_sub,
                            ":u": datetime.utcnow().isoformat(),
                        },
                    )
                except ClientError:
                    pass

                existing["google_sub"] = google_sub
                self._touch_last_login(existing["user_id"])
                return self._issue_token_response(existing)

            # Any other weird case: fail closed
            raise UserAlreadyExistsError(email)

        # 3) Create new Google user
        user_id = str(uuid.uuid4())
        current_time = datetime.utcnow().isoformat()

        user_data = {
            "user_id": user_id,
            "email": email,
            "full_name": full_name,
            "auth_provider": "google",
            "google_sub": google_sub,
            "email_verified": bool(email_verified),
            "created_at": current_time,
            "updated_at": current_time,
            "last_login_at": current_time,
        }

        try:
            self.users_table.put_item(Item=user_data)
        except ClientError as e:
            raise DatabaseError(f"Failed to create Google user: {str(e)}", e)

        return self._issue_token_response(user_data)

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------
    def _issue_token_response(self, user: Dict[str, Any]) -> Dict[str, Any]:
        """
        Given a user item, mint a JWT and return the standard response shape.
        """
        access_token = create_access_token(
            data={"sub": user["user_id"], "email": user["email"]},
            expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
        )

        return {
            "user": {
                "user_id": user["user_id"],
                "email": user["email"],
                "full_name": user.get("full_name"),
                "created_at": user.get("created_at"),
            },
            "access_token": access_token,
        }

    def _touch_last_login(self, user_id: str) -> None:
        """
        Best-effort update of last_login_at. Failure should not block login.
        """
        try:
            self.users_table.update_item(
                Key={"user_id": user_id},
                UpdateExpression="SET last_login_at = :t, updated_at = :t",
                ExpressionAttributeValues={":t": datetime.utcnow().isoformat()},
            )
        except ClientError:
            return

    # -------------------------------------------------------------------------
    # Existing: lookups (scan-based for now)
    # -------------------------------------------------------------------------
    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get user by email (scan for now; replace with GSI later)."""
        try:
            response = self.users_table.scan(
                FilterExpression="email = :email",
                ExpressionAttributeValues={":email": email},
            )
            items = response.get("Items", [])
            return items[0] if items else None
        except ClientError:
            return None

    def get_user_by_google_sub(self, google_sub: str) -> Optional[Dict[str, Any]]:
        """Get user by google_sub (scan for now; replace with GSI later)."""
        try:
            response = self.users_table.scan(
                FilterExpression="google_sub = :gs",
                ExpressionAttributeValues={":gs": google_sub},
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
