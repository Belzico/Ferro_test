import json
import os
import pytest
from pathlib import Path
from app.config import load_settings, RetrySettings, WorkerSettings, DatabaseSettings, Settings
from pydantic import ValidationError


class TestConfiguration:
    """Test suite for application configuration loading and validation."""

    @pytest.fixture
    def valid_config_dict(self):
        """Helper fixture providing a complete valid configuration."""
        return {
            "database": {"url": "sqlite:///./fero_jobs.db"},
            "worker": {"poll_interval_seconds": 1, "http_timeout_seconds": 10, "lease_duration_seconds": 60},
            "retry": {"max_attempts": 5, "initial_delay_seconds": 2, "backoff_multiplier": 2, "max_delay_seconds": 60, "retryable_status_codes": [429, 500, 503]},
            "app": {"name": "FERO Platform", "debug": False}
        }

    def test_load_real_appsettings_json_successfully(self):
        """Successfully load the real appsettings.json file."""
        settings = load_settings()
        assert settings is not None
        assert settings.database.url == "sqlite:///./fero_jobs.db"
        assert settings.worker.poll_interval_seconds == 1
        assert settings.worker.http_timeout_seconds == 10
        assert settings.worker.lease_duration_seconds == 60
        assert settings.retry.max_attempts == 5
        assert settings.retry.initial_delay_seconds == 2
        assert settings.retry.backoff_multiplier == 2
        assert settings.retry.max_delay_seconds == 60
        assert settings.retry.retryable_status_codes == [429, 500, 503]

    def test_configuration_loading_independent_of_cwd(self):
        """Configuration loading should work regardless of current working directory."""
        original_cwd = os.getcwd()
        try:
            # Change to a different directory
            os.chdir(os.path.dirname(os.path.dirname(original_cwd)))
            settings = load_settings()
            assert settings is not None
            assert settings.retry.max_attempts == 5
        finally:
            os.chdir(original_cwd)

    def test_missing_configuration_file_raises_error(self):
        """Attempting to load a non-existent configuration file should raise an error."""
        with pytest.raises(FileNotFoundError):
            load_settings(config_path="nonexistent.json")

    def test_malformed_json_raises_error(self):
        """Malformed JSON should raise an error."""
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("{ invalid json }")
            temp_path = f.name
        
        try:
            with pytest.raises(json.JSONDecodeError):
                load_settings(config_path=temp_path)
        finally:
            os.unlink(temp_path)

    def test_invalid_retry_max_attempts_type_raises_error(self, valid_config_dict):
        """max_attempts must be an integer >= 1, excluding booleans."""
        valid_config_dict["retry"]["max_attempts"] = True
        with pytest.raises(ValidationError):
            Settings(**valid_config_dict)

    def test_invalid_retry_max_attempts_value_raises_error(self, valid_config_dict):
        """max_attempts must be >= 1."""
        valid_config_dict["retry"]["max_attempts"] = 0
        with pytest.raises(ValidationError):
            Settings(**valid_config_dict)

    def test_invalid_retry_initial_delay_raises_error(self, valid_config_dict):
        """initial_delay_seconds must be positive."""
        valid_config_dict["retry"]["initial_delay_seconds"] = 0
        with pytest.raises(ValidationError):
            Settings(**valid_config_dict)

    def test_invalid_retry_backoff_multiplier_raises_error(self, valid_config_dict):
        """backoff_multiplier must be >= 1."""
        valid_config_dict["retry"]["backoff_multiplier"] = 0.5
        with pytest.raises(ValidationError):
            Settings(**valid_config_dict)

    def test_invalid_retry_max_delay_less_than_initial_raises_error(self, valid_config_dict):
        """max_delay_seconds must be >= initial_delay_seconds."""
        valid_config_dict["retry"]["initial_delay_seconds"] = 10
        valid_config_dict["retry"]["max_delay_seconds"] = 5
        with pytest.raises(ValidationError):
            Settings(**valid_config_dict)

    def test_invalid_retryable_status_code_out_of_range_raises_error(self, valid_config_dict):
        """Retryable status codes must be valid HTTP status codes (100-599)."""
        valid_config_dict["retry"]["retryable_status_codes"] = [600]
        with pytest.raises(ValidationError):
            Settings(**valid_config_dict)

    def test_invalid_retryable_status_code_boolean_raises_error(self, valid_config_dict):
        """Retryable status codes must not contain booleans."""
        valid_config_dict["retry"]["retryable_status_codes"] = [True]
        with pytest.raises(ValidationError):
            Settings(**valid_config_dict)

    def test_duplicate_retryable_status_codes_raises_error(self, valid_config_dict):
        """Retryable status codes must not contain duplicates."""
        valid_config_dict["retry"]["retryable_status_codes"] = [429, 500, 500]
        with pytest.raises(ValidationError):
            Settings(**valid_config_dict)

    def test_invalid_worker_poll_interval_raises_error(self, valid_config_dict):
        """poll_interval_seconds must be positive."""
        valid_config_dict["worker"]["poll_interval_seconds"] = 0
        with pytest.raises(ValidationError):
            Settings(**valid_config_dict)

    def test_invalid_worker_http_timeout_raises_error(self, valid_config_dict):
        """http_timeout_seconds must be positive."""
        valid_config_dict["worker"]["http_timeout_seconds"] = 0
        with pytest.raises(ValidationError):
            Settings(**valid_config_dict)

    def test_invalid_worker_lease_duration_less_than_timeout_raises_error(self, valid_config_dict):
        """lease_duration_seconds must be greater than http_timeout_seconds."""
        valid_config_dict["worker"]["lease_duration_seconds"] = 10
        with pytest.raises(ValidationError):
            Settings(**valid_config_dict)

    def test_retry_initial_delay_boolean_raises_error(self, valid_config_dict):
        """initial_delay_seconds must reject booleans."""
        valid_config_dict["retry"]["initial_delay_seconds"] = True
        with pytest.raises(ValidationError):
            Settings(**valid_config_dict)

    def test_retry_initial_delay_string_raises_error(self, valid_config_dict):
        """initial_delay_seconds must reject strings."""
        valid_config_dict["retry"]["initial_delay_seconds"] = "2"
        with pytest.raises(ValidationError):
            Settings(**valid_config_dict)

    def test_retry_backoff_multiplier_boolean_raises_error(self, valid_config_dict):
        """backoff_multiplier must reject booleans."""
        valid_config_dict["retry"]["backoff_multiplier"] = True
        with pytest.raises(ValidationError):
            Settings(**valid_config_dict)

    def test_retry_backoff_multiplier_string_raises_error(self, valid_config_dict):
        """backoff_multiplier must reject strings."""
        valid_config_dict["retry"]["backoff_multiplier"] = "2"
        with pytest.raises(ValidationError):
            Settings(**valid_config_dict)

    def test_worker_poll_interval_boolean_raises_error(self, valid_config_dict):
        """poll_interval_seconds must reject booleans."""
        valid_config_dict["worker"]["poll_interval_seconds"] = True
        with pytest.raises(ValidationError):
            Settings(**valid_config_dict)

    def test_worker_http_timeout_string_raises_error(self, valid_config_dict):
        """http_timeout_seconds must reject strings."""
        valid_config_dict["worker"]["http_timeout_seconds"] = "10"
        with pytest.raises(ValidationError):
            Settings(**valid_config_dict)

    def test_retry_max_delay_boolean_raises_error(self, valid_config_dict):
        """max_delay_seconds must reject booleans."""
        valid_config_dict["retry"]["max_delay_seconds"] = True
        with pytest.raises(ValidationError):
            Settings(**valid_config_dict)

    def test_retryable_status_code_string_raises_error(self):
        """retryable_status_codes must reject strings."""
        config = {
            "database": {"url": "sqlite:///./fero_jobs.db"},
            "worker": {"poll_interval_seconds": 1, "http_timeout_seconds": 10, "lease_duration_seconds": 60},
            "retry": {"max_attempts": 5, "initial_delay_seconds": 2, "backoff_multiplier": 2, "max_delay_seconds": 60, "retryable_status_codes": ["500"]},
            "app": {"name": "FERO Platform", "debug": False}
        }
        with pytest.raises(ValidationError):
            Settings(**config)

    def test_retryable_status_code_float_raises_error(self):
        """retryable_status_codes must reject floats."""
        config = {
            "database": {"url": "sqlite:///./fero_jobs.db"},
            "worker": {"poll_interval_seconds": 1, "http_timeout_seconds": 10, "lease_duration_seconds": 60},
            "retry": {"max_attempts": 5, "initial_delay_seconds": 2, "backoff_multiplier": 2, "max_delay_seconds": 60, "retryable_status_codes": [500.5]},
            "app": {"name": "FERO Platform", "debug": False}
        }
        with pytest.raises(ValidationError):
            Settings(**config)

    def test_complete_valid_configuration_accepted(self, valid_config_dict):
        """A complete valid configuration should be accepted."""
        settings = Settings(**valid_config_dict)
        assert settings.database.url == "sqlite:///./fero_jobs.db"
        assert settings.worker.poll_interval_seconds == 1
        assert settings.retry.max_attempts == 5
        assert settings.app.name == "FERO Platform"

    def test_invalid_http_status_strings_rejected(self, valid_config_dict):
        """Invalid HTTP status strings should be rejected."""
        valid_config_dict["retry"]["retryable_status_codes"] = ["503"]
        with pytest.raises(ValidationError):
            Settings(**valid_config_dict)

    def test_invalid_http_status_booleans_rejected(self, valid_config_dict):
        """Invalid HTTP status booleans should be rejected."""
        valid_config_dict["retry"]["retryable_status_codes"] = [True]
        with pytest.raises(ValidationError):
            Settings(**valid_config_dict)

    def test_invalid_http_status_floats_rejected(self, valid_config_dict):
        """Invalid HTTP status floats should be rejected."""
        valid_config_dict["retry"]["retryable_status_codes"] = [500.5]
        with pytest.raises(ValidationError):
            Settings(**valid_config_dict)

    def test_fastapi_application_imports_and_reads_config(self):
        """FastAPI application should import and read configuration correctly."""
        from app.main import app
        assert app.title == "FERO Platform"
        assert app.debug is False
