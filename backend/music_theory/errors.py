class TheoryError(ValueError):
    """Invalid musical input or an unrepresentable result. `code` is stable for API mapping."""

    code = "theory_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
