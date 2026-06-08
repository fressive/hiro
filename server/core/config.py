"""Application configuration."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(env_file=".env")

    project_name: str = "Hiro API"
    project_description: str = "A scalable FastAPI application"
    version: str = "0.1.0"
    
    # Security
    secret_key: str = "your-secret-key-change-in-production"
    api_key_header: str = "X-API-Key"

    # Installation / LLM configuration
    installation_completed: bool = False
    
    # CORS
    allowed_origins: list = ["*"]
    
    # Database (for future use)
    database_url: str = "sqlite:///./hiro.db"

settings = Settings()
