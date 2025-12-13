"""
Google OAuth (OIDC) routes: login + callback (cookie-based auth).
"""

import base64
import hashlib
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

from App.core.config import settings
from App.services.auth_service import AuthService

router = APIRouter(prefix="/auth/google", tags=["auth"])

# Google's standard endpoints
AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"

auth_service = AuthService()


def _b64url(data: bytes) -> str:
    """
    Base64-url encode without padding. Required by PKCE.
    """
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")


def _pkce_pair() -> tuple[str, str]:
    """
    Create a PKCE verifier + challenge.
    - verifier: random secret stored temporarily (cookie)
    - challenge: SHA256(verifier) sent to Google
    """
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode("utf-8")).digest())
    return verifier, challenge


@router.get("/login")
def google_login():
    """
    Returns a Google authorization URL to redirect the browser to.

    Also sets temporary httpOnly cookies:
      - oauth_state: CSRF protection
      - pkce_verifier: used later to exchange the code
    """
    if not settings.google_client_id or not settings.google_redirect_uri:
        raise HTTPException(status_code=500, detail="Google OAuth not configured")

    state = secrets.token_urlsafe(32)
    verifier, challenge = _pkce_pair()

    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        # "offline" gives refresh tokens (useful later); prompt consent forces refresh token on first time
        "access_type": "offline",
        "prompt": "consent",
    }

    auth_url = f"{AUTH_URI}?{urlencode(params)}"

    resp = JSONResponse({"auth_url": auth_url})

    # Temporary cookies (10 min) used to validate callback
    resp.set_cookie(
        "oauth_state",
        state,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        domain=settings.cookie_domain,
        max_age=10 * 60,
        path="/",
    )
    resp.set_cookie(
        "pkce_verifier",
        verifier,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        domain=settings.cookie_domain,
        max_age=10 * 60,
        path="/",
    )

    return resp


@router.get("/callback")
async def google_callback(request: Request, code: str | None = None, state: str | None = None):
    """
    Google redirects here with ?code=...&state=...

    We:
      1) validate state (CSRF)
      2) exchange code -> tokens with Google's token endpoint
      3) verify id_token signature and claims
      4) login or register the user in our DB
      5) set our app JWT in an httpOnly cookie
      6) redirect to frontend
    """
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code/state")

    cookie_state = request.cookies.get("oauth_state")
    verifier = request.cookies.get("pkce_verifier")

    if not cookie_state or not verifier or state != cookie_state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    if not (settings.google_client_id and settings.google_client_secret and settings.google_redirect_uri):
        raise HTTPException(status_code=500, detail="Google OAuth not configured")

    # Exchange authorization code -> tokens
    data = {
        "code": code,
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "redirect_uri": settings.google_redirect_uri,
        "grant_type": "authorization_code",
        "code_verifier": verifier,
    }

    async with httpx.AsyncClient(timeout=15) as client:
        token_res = await client.post(TOKEN_URI, data=data)

    if token_res.status_code != 200:
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {token_res.text}")

    tokens = token_res.json()
    raw_id_token = tokens.get("id_token")
    if not raw_id_token:
        raise HTTPException(status_code=400, detail="No id_token returned by Google")

    # Verify Google ID token (signature + aud + exp + iss)
    try:
        claims = id_token.verify_oauth2_token(
            raw_id_token,
            google_requests.Request(),
            settings.google_client_id,
        )
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid Google id_token")

    google_sub = claims.get("sub")
    email = claims.get("email")
    full_name = claims.get("name") or ""
    email_verified = bool(claims.get("email_verified", False))

    if not google_sub or not email:
        raise HTTPException(status_code=400, detail="Google token missing sub/email")

    # NOTE: We will implement this method next (AuthService change)
    result = auth_service.login_or_register_google_user(
        google_sub=google_sub,
        email=email,
        full_name=full_name,
        email_verified=email_verified,
    )

    access_token = result["access_token"]

    # Redirect to frontend after successful login
    redirect_url = f"{settings.frontend_url}{settings.frontend_oauth_success_path}"
    resp = RedirectResponse(url=redirect_url, status_code=302)

    # Set your app auth cookie (httpOnly)
    resp.set_cookie(
        settings.access_cookie_name,
        access_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        domain=settings.cookie_domain,
        max_age=settings.access_token_expire_minutes * 60,
        path="/",
    )

    # Clear temporary OAuth cookies
    resp.delete_cookie("oauth_state", path="/", domain=settings.cookie_domain)
    resp.delete_cookie("pkce_verifier", path="/", domain=settings.cookie_domain)

    return resp
