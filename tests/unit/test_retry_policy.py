import pytest
from app.services.retry_policy import RetryPolicy, RetryDecision, TransportFailure
from app.config import RetrySettings, settings


class TestRetryPolicy:
    """Test suite for the deterministic retry policy."""

    @pytest.fixture
    def default_retry_config(self):
        """Default retry configuration for testing."""
        return settings.retry

    @pytest.mark.parametrize("attempt", [0, -1, -10])
    def test_invalid_attempt_raises_value_error(self, attempt, default_retry_config):
        """Attempt numbers less than 1 should raise ValueError."""
        policy = RetryPolicy(default_retry_config)
        with pytest.raises(ValueError, match="Attempt must be at least 1|Attempt must be an integer >= 1"):
            policy.should_retry(attempt=attempt, status_code=500)

    @pytest.mark.parametrize("attempt", [True, False, 1.5, 2.0, "2", None])
    def test_invalid_attempt_type_raises_value_error(self, attempt, default_retry_config):
        """Attempt must be an integer, reject booleans, floats, strings, and None."""
        policy = RetryPolicy(default_retry_config)
        with pytest.raises(ValueError, match="Attempt must be an integer >= 1|Attempt must be at least 1"):
            policy.should_retry(attempt=attempt, status_code=500)

    @pytest.mark.parametrize("status_code", [99, 0, -1, 600, 1000])
    def test_invalid_status_code_raises_value_error(self, status_code, default_retry_config):
        """Status codes outside 100-599 range should raise ValueError."""
        policy = RetryPolicy(default_retry_config)
        with pytest.raises(ValueError, match="Status code must be between 100 and 599"):
            policy.should_retry(attempt=1, status_code=status_code)

    @pytest.mark.parametrize("status_code", [True, False])
    def test_boolean_status_code_raises_value_error(self, status_code, default_retry_config):
        """Boolean status codes should raise ValueError (reject booleans)."""
        policy = RetryPolicy(default_retry_config)
        with pytest.raises(ValueError, match="Status code must be between 100 and 599"):
            policy.should_retry(attempt=1, status_code=status_code)

    def test_both_status_code_and_transport_failure_raises_value_error(self, default_retry_config):
        """Providing both status_code and transport_failure should raise ValueError."""
        policy = RetryPolicy(default_retry_config)
        with pytest.raises(ValueError, match="Provide either status_code or transport_failure, not both"):
            policy.should_retry(
                attempt=1,
                status_code=500,
                transport_failure=TransportFailure.CONNECTION_ERROR
            )

    def test_neither_status_code_nor_transport_failure_raises_value_error(self, default_retry_config):
        """Providing neither status_code nor transport_failure should raise ValueError."""
        policy = RetryPolicy(default_retry_config)
        with pytest.raises(ValueError, match="Provide either status_code or transport_failure"):
            policy.should_retry(attempt=1, status_code=None, transport_failure=None)

    def test_invalid_transport_failure_type_raises_value_error(self, default_retry_config):
        """Non-TransportFailure enum value should raise ValueError."""
        policy = RetryPolicy(default_retry_config)
        with pytest.raises(ValueError, match="transport_failure must be a TransportFailure enum"):
            policy.should_retry(attempt=1, status_code=None, transport_failure="invalid")

    @pytest.mark.parametrize("status_code", [200, 201, 204])
    def test_successful_responses_no_retry(self, status_code, default_retry_config):
        """Successful responses should not trigger retries."""
        policy = RetryPolicy(default_retry_config)
        decision = policy.should_retry(attempt=1, status_code=status_code)
        assert decision.should_retry is False
        assert decision.next_backoff_seconds is None

    @pytest.mark.parametrize("status_code", [429, 500, 503])
    def test_retryable_status_codes_retry(self, status_code, default_retry_config):
        """HTTP 429, 500, and 503 should trigger retry."""
        policy = RetryPolicy(default_retry_config)
        decision = policy.should_retry(attempt=1, status_code=status_code)
        assert decision.should_retry is True
        assert decision.next_backoff_seconds == 2

    @pytest.mark.parametrize("status_code", [400, 401, 403, 404, 405, 409, 422])
    def test_permanent_failures_no_retry(self, status_code, default_retry_config):
        """Permanent errors should not trigger retries."""
        policy = RetryPolicy(default_retry_config)
        decision = policy.should_retry(attempt=1, status_code=status_code)
        assert decision.should_retry is False
        assert decision.next_backoff_seconds is None

    @pytest.mark.parametrize(
        "attempt,expected_backoff",
        [(1, 2), (2, 4), (3, 8), (4, 16)]
    )
    def test_exponential_backoff_sequence(self, attempt, expected_backoff, default_retry_config):
        """Backoff progression: 2, 4, 8, 16 seconds for attempts 1-4."""
        policy = RetryPolicy(default_retry_config)
        decision = policy.should_retry(attempt=attempt, status_code=500)
        assert decision.should_retry is True
        assert decision.next_backoff_seconds == expected_backoff

    def test_attempt_5_no_retry(self, default_retry_config):
        """Fifth attempt should not trigger retry (max attempts exhausted)."""
        policy = RetryPolicy(default_retry_config)
        decision = policy.should_retry(attempt=5, status_code=500)
        assert decision.should_retry is False
        assert decision.next_backoff_seconds is None

    def test_attempt_beyond_5_no_retry(self, default_retry_config):
        """Attempts beyond 5 should not trigger retry."""
        policy = RetryPolicy(default_retry_config)
        decision = policy.should_retry(attempt=6, status_code=500)
        assert decision.should_retry is False
        assert decision.next_backoff_seconds is None

    @pytest.mark.parametrize("attempt", [1, 2, 3, 4])
    def test_transport_connection_failure_retry(self, attempt, default_retry_config):
        """Connection failures should be retryable while attempts remain."""
        policy = RetryPolicy(default_retry_config)
        decision = policy.should_retry(
            attempt=attempt,
            status_code=None,
            transport_failure=TransportFailure.CONNECTION_ERROR
        )
        assert decision.should_retry is True
        expected_backoff = [2, 4, 8, 16][attempt - 1]
        assert decision.next_backoff_seconds == expected_backoff

    @pytest.mark.parametrize("attempt", [1, 2, 3, 4])
    def test_transport_timeout_retry(self, attempt, default_retry_config):
        """Timeout failures should be retryable while attempts remain."""
        policy = RetryPolicy(default_retry_config)
        decision = policy.should_retry(
            attempt=attempt,
            status_code=None,
            transport_failure=TransportFailure.TIMEOUT
        )
        assert decision.should_retry is True
        expected_backoff = [2, 4, 8, 16][attempt - 1]
        assert decision.next_backoff_seconds == expected_backoff

    def test_transport_failure_attempt_5_no_retry(self, default_retry_config):
        """Transport failures on attempt 5 should not retry."""
        policy = RetryPolicy(default_retry_config)
        decision = policy.should_retry(
            attempt=5,
            status_code=None,
            transport_failure=TransportFailure.CONNECTION_ERROR
        )
        assert decision.should_retry is False
        assert decision.next_backoff_seconds is None

    def test_max_attempts_constant(self, default_retry_config):
        """Verify maximum attempts is exactly 5."""
        policy = RetryPolicy(default_retry_config)
        assert policy.max_attempts == 5

    def test_backoff_defaults_to_2_4_8_16_seconds(self, default_retry_config):
        """Default backoff sequence should be 2, 4, 8, 16 seconds."""
        policy = RetryPolicy(default_retry_config)
        
        expected_backoffs = [2, 4, 8, 16]
        for attempt, expected_backoff in enumerate(expected_backoffs, start=1):
            decision = policy.should_retry(attempt=attempt, status_code=500)
            assert decision.should_retry is True
            assert decision.next_backoff_seconds == expected_backoff

    def test_no_retry_after_attempt_5(self, default_retry_config):
        """Fifth attempt should not trigger retry (max attempts exhausted)."""
        policy = RetryPolicy(default_retry_config)
        decision = policy.should_retry(attempt=5, status_code=500)
        assert decision.should_retry is False
        assert decision.next_backoff_seconds is None

    def test_custom_initial_delay_changes_sequence(self):
        """Custom initial delay should change the backoff sequence."""
        retry_config = RetrySettings(
            max_attempts=5,
            initial_delay_seconds=3,
            backoff_multiplier=2,
            max_delay_seconds=60,
            retryable_status_codes=[429, 500, 503]
        )
        policy = RetryPolicy(retry_config)
        
        expected_backoffs = [3, 6, 12, 24]
        for attempt, expected_backoff in enumerate(expected_backoffs, start=1):
            decision = policy.should_retry(attempt=attempt, status_code=500)
            assert decision.should_retry is True
            assert decision.next_backoff_seconds == expected_backoff

    def test_custom_multiplier_changes_sequence(self):
        """Custom multiplier should change the backoff sequence."""
        retry_config = RetrySettings(
            max_attempts=5,
            initial_delay_seconds=2,
            backoff_multiplier=3,
            max_delay_seconds=60,
            retryable_status_codes=[429, 500, 503]
        )
        policy = RetryPolicy(retry_config)
        
        expected_backoffs = [2, 6, 18, 54]
        for attempt, expected_backoff in enumerate(expected_backoffs, start=1):
            decision = policy.should_retry(attempt=attempt, status_code=500)
            assert decision.should_retry is True
            assert decision.next_backoff_seconds == expected_backoff

    def test_maximum_backoff_cap_works(self):
        """Backoff should be capped at max_delay_seconds."""
        retry_config = RetrySettings(
            max_attempts=5,
            initial_delay_seconds=10,
            backoff_multiplier=4,
            max_delay_seconds=30,
            retryable_status_codes=[429, 500, 503]
        )
        policy = RetryPolicy(retry_config)
        
        # Without cap: 10, 40, 160, 640
        # With cap at 30: 10, 30, 30, 30
        expected_backoffs = [10, 30, 30, 30]
        for attempt, expected_backoff in enumerate(expected_backoffs, start=1):
            decision = policy.should_retry(attempt=attempt, status_code=500)
            assert decision.should_retry is True
            assert decision.next_backoff_seconds == expected_backoff

    def test_custom_maximum_attempts_work(self):
        """Custom max_attempts should be respected."""
        retry_config = RetrySettings(
            max_attempts=3,
            initial_delay_seconds=2,
            backoff_multiplier=2,
            max_delay_seconds=60,
            retryable_status_codes=[429, 500, 503]
        )
        policy = RetryPolicy(retry_config)
        
        # Attempt 1 and 2 should retry
        for attempt in [1, 2]:
            decision = policy.should_retry(attempt=attempt, status_code=500)
            assert decision.should_retry is True
        
        # Attempt 3 should not retry
        decision = policy.should_retry(attempt=3, status_code=500)
        assert decision.should_retry is False
        assert decision.next_backoff_seconds is None

    def test_configured_retryable_status_codes_are_respected(self):
        """Configured retryable status codes should be respected."""
        retry_config = RetrySettings(
            max_attempts=5,
            initial_delay_seconds=2,
            backoff_multiplier=2,
            max_delay_seconds=60,
            retryable_status_codes=[502, 503]  # Custom set
        )
        policy = RetryPolicy(retry_config)
        
        # 502 and 503 should retry
        for code in [502, 503]:
            decision = policy.should_retry(attempt=1, status_code=code)
            assert decision.should_retry is True
        
        # 429 and 500 should not retry (not in configured list)
        for code in [429, 500]:
            decision = policy.should_retry(attempt=1, status_code=code)
            assert decision.should_retry is False

    def test_recognized_transport_failures_remain_retryable(self, default_retry_config):
        """Transport failures should remain retryable with custom config."""
        policy = RetryPolicy(default_retry_config)
        
        for failure in [TransportFailure.CONNECTION_ERROR, TransportFailure.TIMEOUT]:
            decision = policy.should_retry(attempt=1, status_code=None, transport_failure=failure)
            assert decision.should_retry is True
            assert decision.next_backoff_seconds == 2

    def test_existing_input_validation_remains_intact(self, default_retry_config):
        """Existing input validation should remain intact with custom config."""
        policy = RetryPolicy(default_retry_config)
        
        # Invalid attempt
        with pytest.raises(ValueError, match="Attempt must be at least 1"):
            policy.should_retry(attempt=0, status_code=500)
        
        # Invalid status code
        with pytest.raises(ValueError, match="Status code must be between 100 and 599"):
            policy.should_retry(attempt=1, status_code=600)
        
        # Both status_code and transport_failure
        with pytest.raises(ValueError, match="Provide either status_code or transport_failure, not both"):
            policy.should_retry(attempt=1, status_code=500, transport_failure=TransportFailure.CONNECTION_ERROR)

    def test_policy_is_deterministic(self, default_retry_config):
        """Calling the policy twice with identical inputs produces identical decisions."""
        policy = RetryPolicy(default_retry_config)
        
        decision1 = policy.should_retry(attempt=2, status_code=500)
        decision2 = policy.should_retry(attempt=2, status_code=500)
        
        assert decision1.should_retry == decision2.should_retry
        assert decision1.next_backoff_seconds == decision2.next_backoff_seconds

    def test_large_multiplier_reaches_cap_correctly(self):
        """Large multipliers should reach the configured cap correctly."""
        retry_config = RetrySettings(
            max_attempts=10,
            initial_delay_seconds=1,
            backoff_multiplier=10,
            max_delay_seconds=100,
            retryable_status_codes=[429, 500, 503]
        )
        policy = RetryPolicy(retry_config)
        
        # Without cap: 1, 10, 100, 1000, 10000...
        # With cap at 100: 1, 10, 100, 100, 100...
        expected_backoffs = [1, 10, 100, 100, 100, 100, 100, 100, 100]
        for attempt, expected_backoff in enumerate(expected_backoffs, start=1):
            decision = policy.should_retry(attempt=attempt, status_code=500)
            assert decision.should_retry is True
            assert decision.next_backoff_seconds == expected_backoff

    def test_large_attempt_number_with_large_max_attempts(self):
        """Large attempt numbers with suitably configured max_attempts should work without excessive computation."""
        retry_config = RetrySettings(
            max_attempts=100,
            initial_delay_seconds=1,
            backoff_multiplier=2,
            max_delay_seconds=300,
            retryable_status_codes=[429, 500, 503]
        )
        policy = RetryPolicy(retry_config)
        
        # Verify attempt 50 works (should be capped at 300)
        decision = policy.should_retry(attempt=50, status_code=500)
        assert decision.should_retry is True
        assert decision.next_backoff_seconds == 300

    def test_changing_max_delay_changes_cap(self):
        """Changing max_delay_seconds should change the cap with different outcomes."""
        retry_config1 = RetrySettings(
            max_attempts=6,
            initial_delay_seconds=2,
            backoff_multiplier=2,
            max_delay_seconds=10,
            retryable_status_codes=[429, 500, 503]
        )
        policy1 = RetryPolicy(retry_config1)
        
        retry_config2 = RetrySettings(
            max_attempts=6,
            initial_delay_seconds=2,
            backoff_multiplier=2,
            max_delay_seconds=30,
            retryable_status_codes=[429, 500, 503]
        )
        policy2 = RetryPolicy(retry_config2)
        
        # Attempt 5 with cap 10: min(16, 10) = 10
        decision1 = policy1.should_retry(attempt=5, status_code=500)
        assert decision1.next_backoff_seconds == 10
        
        # Attempt 5 with cap 30: min(32, 30) = 30
        decision2 = policy2.should_retry(attempt=5, status_code=500)
        assert decision2.should_retry is True
        assert decision2.next_backoff_seconds == 30
