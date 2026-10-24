class ExtractionError(Exception):
    """A processing failure with a user-safe message.

    `retryable` distinguishes transient faults (provider timeout, rate limit, malformed model
    output that may succeed on retry) from permanent ones (unsupported or unreadable file).
    Messages must never contain document content.
    """

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
