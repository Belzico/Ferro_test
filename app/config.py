from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application configuration using Pydantic Settings."""
    
    APP_NAME: str = "FERO Platform"
    DEBUG: bool = False
    
    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
