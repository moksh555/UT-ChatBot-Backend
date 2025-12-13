"""
Application configuration.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import List, Optional
from pathlib import Path


class Settings(BaseSettings):
    """Application settings."""

    
    
    # AWS
    aws_access_key_id: str = Field(..., env="AWS_ACCESS_KEY_ID")
    aws_secret_access_key: str = Field(..., env="AWS_SECRET_ACCESS_KEY")
    aws_region: str = Field(default="us-east-1", env="AWS_DEFAULT_REGION")
    
    # DynamoDB Tables
    checkpointer_table: str = Field(..., env="CHECKPOINTER_TABLE")
    user_personal_history: str = Field(..., env="USER_PERSONAL_HISTORY")
    users_table: str = Field(default="langgraph-users", env="USERS_TABLE")
    
    # JWT Settings
    secret_key: str = Field(..., env="SECRET_KEY")
    algorithm: str = Field(default="HS256", env="ALGORITHM")
    access_token_expire_minutes: int = Field(default=30, env="ACCESS_TOKEN_EXPIRE_MINUTES")
    
    #google OAuth Settings
    # Google OAuth (OpenID Connect)
    google_client_id: str = Field(..., env="GOOGLE_CLIENT_ID")
    google_client_secret: str = Field(..., env="GOOGLE_CLIENT_SECRET")
    google_redirect_uri: str = Field(..., env="GOOGLE_REDIRECT_URI")

    # Frontend + cookies (Option A: httpOnly cookie + redirect)
    frontend_url: str = Field(default="http://localhost:5173", env="FRONTEND_URL")
    frontend_oauth_success_path: str = Field(default="/dashboard", env="FRONTEND_OAUTH_SUCCESS_PATH")

    cookie_secure: bool = Field(default=False, env="COOKIE_SECURE")  # True in prod (HTTPS)
    cookie_samesite: str = Field(default="lax", env="COOKIE_SAMESITE")  # usually "lax"
    cookie_domain: Optional[str] = Field(default=None, env="COOKIE_DOMAIN")  # e.g. ".texascollegeguides.com"
    access_cookie_name: str = Field(default="access_token", env="ACCESS_COOKIE_NAME")


    # API
    app_name: str = "Texas College ChatBot API"
    app_version: str = "1.0.0"

    allowed_origins: List[str] = Field(
        default_factory=list,
        env="ALLOWED_ORIGINS",
    )
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

settings = Settings()