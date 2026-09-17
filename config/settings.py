import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

# Get the directory where this settings.py file is located, then go up one level to the project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_FILE = os.path.join(PROJECT_ROOT, ".env")

class Settings(BaseSettings):
    mongodb_uri: Optional[str] = None
    cors_origins: str = "http://localhost:5173"
    groq_chatbot_api_key: Optional[str] = None
    groq_resume_parser_api_key: Optional[str] = None
    adzuna_app_id: Optional[str] = None
    adzuna_app_key: Optional[str] = None

    # Supabase Auth. The JWKS URL and issuer are derived from the project URL.
    # supabase_jwt_secret is only needed as a fallback for projects that still
    # sign tokens with the legacy HS256 shared secret instead of asymmetric
    # (RS256/ES256) signing keys.
    supabase_url: Optional[str] = None
    supabase_jwt_secret: Optional[str] = None
    # Admin (service_role) key — server-only, never exposed to the frontend.
    # Required for account deletion (Supabase Admin API).
    supabase_service_role_key: Optional[str] = None

    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    @property
    def supabase_jwks_url(self) -> Optional[str]:
        if not self.supabase_url:
            return None
        return f"{self.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"

    @property
    def supabase_issuer(self) -> Optional[str]:
        if not self.supabase_url:
            return None
        return f"{self.supabase_url.rstrip('/')}/auth/v1"

settings = Settings()
