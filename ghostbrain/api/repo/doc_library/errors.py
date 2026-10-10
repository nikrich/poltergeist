"""Library errors. Each carries its HTTP status so the routes map them 1:1."""


class LibraryError(Exception):
    status = 400


class InvalidPath(LibraryError):
    status = 400


class InvalidRequest(LibraryError):
    status = 400


class NotFound(LibraryError):
    status = 404


class Conflict(LibraryError):
    status = 409


class TooLarge(LibraryError):
    status = 413
