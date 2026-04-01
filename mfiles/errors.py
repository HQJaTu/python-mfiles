"""Custom exceptions."""

class MFilesException(Exception):
    """
    M-Files base exception.
    """

class MFilesClientException(MFilesException):
    """
    M-Files exception originating from client.
    """

class MFilesServerException(MFilesException):
    """
    M-Files exception originating from server.
    """
