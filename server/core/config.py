"""Application configuration."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings."""

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

    class Config:
        env_file = ".env"

settings = Settings()
