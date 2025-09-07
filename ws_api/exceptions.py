class CurlException(Exception):  # noqa: N818
    pass


class ManualLoginRequired(Exception):  # noqa: N818
    pass


class OTPRequiredException(Exception):  # noqa: N818
    pass


class UnexpectedException(Exception):  # noqa: N818
    pass


class WSApiException(Exception):  # noqa: N818
    def __init__(self, message: str, response=None):
        """
        Initialize the WSApiException.

        :param message: The error message.
        :param code: The error code.
        :param response: Optional response data associated with the exception.
        """
        super().__init__(message)
        self.response = response

    def __str__(self):
        return f"{super().__str__()}; Response: {self.response}"


class LoginFailedException(WSApiException):
    pass
