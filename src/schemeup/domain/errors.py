"""Errors the user can act on. The UI catches these at its boundaries."""


class SchemeUpError(Exception):
    pass


class NotFoundError(SchemeUpError):
    pass


class ConflictError(SchemeUpError):
    pass


class StorageError(SchemeUpError):
    pass


class UnsupportedFormatError(SchemeUpError):
    pass


class ExportError(SchemeUpError):
    pass
