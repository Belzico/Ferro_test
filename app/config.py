import json
from pathlib import Path
from typing import List
from pydantic import BaseModel, field_validator, StrictInt


class DatabaseSettings(BaseModel):
    """Database configuration."""
    url: str


class AppSettings(BaseModel):
    """Application configuration."""
    name: str
    debug: bool


class WorkerSettings(BaseModel):
    """Worker configuration."""
    poll_interval_seconds: int
    http_timeout_seconds: int
    lease_duration_seconds: int

    @field_validator('poll_interval_seconds', mode='before')
    @classmethod
    def poll_interval_must_be_integer(cls, v) -> int:
        if isinstance(v, bool):
            raise ValueError("poll_interval_seconds must be an integer")
        if not isinstance(v, int):
            raise ValueError("poll_interval_seconds must be an integer")
        return v

    @field_validator('poll_interval_seconds')
    @classmethod
    def poll_interval_must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        return v

    @field_validator('http_timeout_seconds', mode='before')
    @classmethod
    def http_timeout_must_be_integer(cls, v) -> int:
        if isinstance(v, bool):
            raise ValueError("http_timeout_seconds must be an integer")
        if not isinstance(v, int):
            raise ValueError("http_timeout_seconds must be an integer")
        return v

    @field_validator('http_timeout_seconds')
    @classmethod
    def http_timeout_must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("http_timeout_seconds must be positive")
        return v

    @field_validator('lease_duration_seconds', mode='before')
    @classmethod
    def lease_duration_must_be_integer(cls, v) -> int:
        if isinstance(v, bool):
            raise ValueError("lease_duration_seconds must be an integer")
        if not isinstance(v, int):
            raise ValueError("lease_duration_seconds must be an integer")
        return v

    @field_validator('lease_duration_seconds')
    @classmethod
    def lease_duration_must_exceed_timeout(cls, v: int, info) -> int:
        if 'http_timeout_seconds' in info.data and v <= info.data['http_timeout_seconds']:
            raise ValueError("lease_duration_seconds must be greater than http_timeout_seconds")
        return v


class RetrySettings(BaseModel):
    """Retry policy configuration."""
    max_attempts: int
    initial_delay_seconds: int
    backoff_multiplier: int
    max_delay_seconds: int
    retryable_status_codes: List[StrictInt]

    @field_validator('max_attempts', mode='before')
    @classmethod
    def max_attempts_must_be_valid(cls, v) -> int:
        if isinstance(v, bool):
            raise ValueError("max_attempts must be an integer >= 1")
        if not isinstance(v, int):
            raise ValueError("max_attempts must be an integer >= 1")
        if v < 1:
            raise ValueError("max_attempts must be >= 1")
        return v

    @field_validator('initial_delay_seconds', mode='before')
    @classmethod
    def initial_delay_must_be_integer(cls, v) -> int:
        if isinstance(v, bool):
            raise ValueError("initial_delay_seconds must be an integer")
        if not isinstance(v, int):
            raise ValueError("initial_delay_seconds must be an integer")
        return v

    @field_validator('initial_delay_seconds')
    @classmethod
    def initial_delay_must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("initial_delay_seconds must be positive")
        return v

    @field_validator('backoff_multiplier', mode='before')
    @classmethod
    def backoff_multiplier_must_be_integer(cls, v) -> int:
        if isinstance(v, bool):
            raise ValueError("backoff_multiplier must be an integer")
        if not isinstance(v, int):
            raise ValueError("backoff_multiplier must be an integer")
        return v

    @field_validator('backoff_multiplier')
    @classmethod
    def backoff_multiplier_must_be_valid(cls, v: int) -> int:
        if v < 1:
            raise ValueError("backoff_multiplier must be >= 1")
        return v

    @field_validator('max_delay_seconds', mode='before')
    @classmethod
    def max_delay_must_be_integer(cls, v) -> int:
        if isinstance(v, bool):
            raise ValueError("max_delay_seconds must be an integer")
        if not isinstance(v, int):
            raise ValueError("max_delay_seconds must be an integer")
        return v

    @field_validator('max_delay_seconds')
    @classmethod
    def max_delay_must_exceed_initial(cls, v: int, info) -> int:
        if 'initial_delay_seconds' in info.data and v < info.data['initial_delay_seconds']:
            raise ValueError("max_delay_seconds must be >= initial_delay_seconds")
        return v

    @field_validator('retryable_status_codes')
    @classmethod
    def retryable_status_codes_must_be_valid(cls, v: List[StrictInt]) -> List[StrictInt]:
        if len(v) != len(set(v)):
            raise ValueError("retryable_status_codes must not contain duplicates")
        for code in v:
            if not 100 <= code <= 599:
                raise ValueError("retryable_status_codes must be valid HTTP status codes (100-599)")
        return v


class Settings(BaseModel):
    """Root application configuration."""
    database: DatabaseSettings
    worker: WorkerSettings
    retry: RetrySettings
    app: AppSettings


def load_settings(config_path: str = None) -> Settings:
    """Load application settings from JSON configuration file.
    
    Args:
        config_path: Optional path to configuration file. If not provided,
                    loads from app/appsettings.json relative to this file.
    
    Returns:
        Settings object with loaded configuration
    
    Raises:
        FileNotFoundError: If configuration file does not exist
        json.JSONDecodeError: If configuration file is not valid JSON
        ValueError: If configuration values are invalid
    """
    if config_path is None:
        # Resolve path relative to this config.py file, not current working directory
        config_dir = Path(__file__).parent
        config_path = config_dir / "appsettings.json"
    else:
        config_path = Path(config_path)
    
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    
    with open(config_path, 'r') as f:
        config_data = json.load(f)
    
    return Settings(**config_data)


# Load default settings
settings = load_settings()
