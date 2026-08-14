"""Shared database and domain exceptions."""


class NotFoundError(Exception):
    """Raised when a requested entity does not exist."""


class ConflictError(Exception):
    """Raised when an operation violates a uniqueness or state constraint."""


class ValidationError(Exception):
    """Raised when a domain rule fails outside Pydantic validation."""
