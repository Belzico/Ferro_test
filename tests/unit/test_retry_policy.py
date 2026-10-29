import pytest
from app.services.retry_policy import RetryPolicy, RetryDecision, TransportFailure


class TestRetryPolicy:
    """Test suite for the deterministic retry policy."""

    @pytest.mark.parametrize("attempt", [0, -1, -10])
    def test_invalid_attempt_raises_value_error(self, attempt):
        """Attempt numbers less than 1 should raise ValueError."""
        policy = RetryPolicy()
        with pytest.raises(ValueError, match="Attempt must be at least 1"):
            policy.should_retry(attempt=attempt, status_code=500)

    @pytest.mark.parametrize("attempt", [True, False, 1.5, 2.0, "2", None])
    def test_invalid_attempt_type_raises_value_error(self, attempt):
        """Attempt must be an integer, reject booleans, floats, strings, and None."""
        policy = RetryPolicy()
        with pytest.raises(ValueError, match="Attempt must be an integer >= 1"):
            policy.should_retry(attempt=attempt, status_code=500)

    @pytest.mark.parametrize("status_code", [99, 0, -1, 600, 1000])
    def test_invalid_status_code_raises_value_error(self, status_code):
        """Status codes outside 100-599 range should raise ValueError."""
        policy = RetryPolicy()
        with pytest.raises(ValueError, match="Status code must be between 100 and 599"):
            policy.should_retry(attempt=1, status_code=status_code)

    @pytest.mark.parametrize("status_code", [True, False])
    def test_boolean_status_code_raises_value_error(self, status_code):
        """Boolean status codes should raise ValueError (reject booleans)."""
        policy = RetryPolicy()
        with pytest.raises(ValueError, match="Status code must be between 100 and 599"):
            policy.should_retry(attempt=1, status_code=status_code)

    def test_both_status_code_and_transport_failure_raises_value_error(self):
        """Providing both status_code and transport_failure should raise ValueError."""
        policy = RetryPolicy()
        with pytest.raises(ValueError, match="Provide either status_code or transport_failure, not both"):
            policy.should_retry(
                attempt=1,
                status_code=500,
                transport_failure=TransportFailure.CONNECTION_ERROR
            )

    def test_neither_status_code_nor_transport_failure_raises_value_error(self):
        """Providing neither status_code nor transport_failure should raise ValueError."""
        policy = RetryPolicy()
        with pytest.raises(ValueError, match="Provide either status_code or transport_failure"):
            policy.should_retry(attempt=1, status_code=None, transport_failure=None)

    def test_invalid_transport_failure_type_raises_value_error(self):
        """Non-TransportFailure enum value should raise ValueError."""
        policy = RetryPolicy()
        with pytest.raises(ValueError, match="transport_failure must be a TransportFailure enum"):
            policy.should_retry(attempt=1, status_code=None, transport_failure="invalid")

    @pytest.mark.parametrize("status_code", [200, 201, 204])
    def test_successful_responses_no_retry(self, status_code):
        """Successful responses should not trigger retries."""
        policy = RetryPolicy()
        decision = policy.should_retry(attempt=1, status_code=status_code)
        assert decision.should_retry is False
        assert decision.next_backoff_seconds is None

    @pytest.mark.parametrize("status_code", [429, 500, 503])
    def test_retryable_status_codes_retry(self, status_code):
        """HTTP 429, 500, and 503 should trigger retry."""
        policy = RetryPolicy()
        decision = policy.should_retry(attempt=1, status_code=status_code)
        assert decision.should_retry is True
        assert decision.next_backoff_seconds == 2

    @pytest.mark.parametrize("status_code", [400, 401, 403, 404, 405, 409, 422])
    def test_permanent_failures_no_retry(self, status_code):
        """Permanent errors should not trigger retries."""
        policy = RetryPolicy()
        decision = policy.should_retry(attempt=1, status_code=status_code)
        assert decision.should_retry is False
        assert decision.next_backoff_seconds is None

    @pytest.mark.parametrize(
        "attempt,expected_backoff",
        [(1, 2), (2, 4), (3, 8), (4, 16)]
    )
    def test_exponential_backoff_sequence(self, attempt, expected_backoff):
        """Backoff progression: 2, 4, 8, 16 seconds for attempts 1-4."""
        policy = RetryPolicy()
        decision = policy.should_retry(attempt=attempt, status_code=500)
        assert decision.should_retry is True
        assert decision.next_backoff_seconds == expected_backoff

    def test_attempt_5_no_retry(self):
        """Fifth attempt should not trigger retry (max attempts exhausted)."""
        policy = RetryPolicy()
        decision = policy.should_retry(attempt=5, status_code=500)
        assert decision.should_retry is False
        assert decision.next_backoff_seconds is None

    def test_attempt_beyond_5_no_retry(self):
        """Attempts beyond 5 should not trigger retry."""
        policy = RetryPolicy()
        decision = policy.should_retry(attempt=6, status_code=500)
        assert decision.should_retry is False
        assert decision.next_backoff_seconds is None

    @pytest.mark.parametrize("attempt", [1, 2, 3, 4])
    def test_transport_connection_failure_retry(self, attempt):
        """Connection failures should be retryable while attempts remain."""
        policy = RetryPolicy()
        decision = policy.should_retry(
            attempt=attempt,
            status_code=None,
            transport_failure=TransportFailure.CONNECTION_ERROR
        )
        assert decision.should_retry is True
        expected_backoff = [2, 4, 8, 16][attempt - 1]
        assert decision.next_backoff_seconds == expected_backoff

    @pytest.mark.parametrize("attempt", [1, 2, 3, 4])
    def test_transport_timeout_retry(self, attempt):
        """Timeout failures should be retryable while attempts remain."""
        policy = RetryPolicy()
        decision = policy.should_retry(
            attempt=attempt,
            status_code=None,
            transport_failure=TransportFailure.TIMEOUT
        )
        assert decision.should_retry is True
        expected_backoff = [2, 4, 8, 16][attempt - 1]
        assert decision.next_backoff_seconds == expected_backoff

    def test_transport_failure_attempt_5_no_retry(self):
        """Transport failures on attempt 5 should not retry."""
        policy = RetryPolicy()
        decision = policy.should_retry(
            attempt=5,
            status_code=None,
            transport_failure=TransportFailure.CONNECTION_ERROR
        )
        assert decision.should_retry is False
        assert decision.next_backoff_seconds is None

    def test_max_attempts_constant(self):
        """Verify maximum attempts is exactly 5."""
        policy = RetryPolicy()
        assert policy.max_attempts == 5
