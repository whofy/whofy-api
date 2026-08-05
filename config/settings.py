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
    clerk_secret_key: Optional[str] = None

    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

settings = Settings()
