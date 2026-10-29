from dataclasses import dataclass
from enum import Enum
from typing import Optional


class TransportFailure(Enum):
    """Represents recoverable transport-level failures."""
    CONNECTION_ERROR = "connection_error"
    TIMEOUT = "timeout"


@dataclass
class RetryDecision:
    """Represents a retry decision with backoff information."""
    should_retry: bool
    next_backoff_seconds: Optional[int] = None


class RetryPolicy:
    """Deterministic retry policy for HTTP requests.
    
    Rules:
    - Retry HTTP 429, 500, and 503 status codes
    - Retry transport failures (connection errors, timeouts)
    - Do not retry non-transient errors (400, 404, etc.)
    - Maximum 5 total execution attempts (attempts 1-5)
    - Exponential backoff: 2, 4, 8, 16 seconds for attempts 1-4
    - No retries after attempt 5
    - Attempt must be an integer >= 1 (booleans, floats, strings, None rejected)
    - Must provide exactly one of: status_code or transport_failure
    - Status codes must be integers between 100 and 599 (booleans rejected)
    """
    
    MAX_ATTEMPTS = 5
    RETRYABLE_STATUS_CODES = {429, 500, 503}
    BACKOFF_SECONDS = [2, 4, 8, 16]
    
    @property
    def max_attempts(self) -> int:
        """Maximum number of execution attempts."""
        return self.MAX_ATTEMPTS
    
    def should_retry(
        self,
        attempt: int,
        status_code: Optional[int] = None,
        transport_failure: Optional[TransportFailure] = None
    ) -> RetryDecision:
        """Determine if a request should be retried.
        
        Args:
            attempt: Current attempt number (1-indexed, must be integer >= 1)
            status_code: Optional HTTP status code from the response (must be 100-599, not bool)
            transport_failure: Optional transport failure type (must be TransportFailure enum)
        
        Returns:
            RetryDecision with should_retry flag and backoff seconds
        
        Raises:
            ValueError: If any parameter is invalid
        """
        # Validate attempt type and value
        if isinstance(attempt, bool):
            raise ValueError("Attempt must be an integer >= 1")
        if not isinstance(attempt, int):
            raise ValueError("Attempt must be an integer >= 1")
        if attempt < 1:
            raise ValueError("Attempt must be at least 1")
        
        # Validate exactly one execution outcome is provided
        if status_code is not None and transport_failure is not None:
            raise ValueError("Provide either status_code or transport_failure, not both")
        
        if status_code is None and transport_failure is None:
            raise ValueError("Provide either status_code or transport_failure")
        
        # Validate status_code
        if status_code is not None:
            if isinstance(status_code, bool):
                raise ValueError("Status code must be between 100 and 599")
            if not isinstance(status_code, int):
                raise ValueError("Status code must be between 100 and 599")
            if not 100 <= status_code <= 599:
                raise ValueError("Status code must be between 100 and 599")
        
        # Validate transport_failure
        if transport_failure is not None:
            if not isinstance(transport_failure, TransportFailure):
                raise ValueError("transport_failure must be a TransportFailure enum")
        
        # Check if we've exceeded max attempts
        if attempt >= self.MAX_ATTEMPTS:
            return RetryDecision(should_retry=False)
        
        # Determine if retry is warranted based on status code or transport failure
        if status_code is not None:
            if status_code not in self.RETRYABLE_STATUS_CODES:
                return RetryDecision(should_retry=False)
        
        # Calculate backoff for this attempt (attempts 1-4 map to indices 0-3)
        backoff_index = attempt - 1
        backoff = self.BACKOFF_SECONDS[backoff_index]
        return RetryDecision(should_retry=True, next_backoff_seconds=backoff)
