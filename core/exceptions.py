"""Errors at tool definition, discovery and validation boundaries."""

from copy import deepcopy


class ToolDefinitionError(ValueError):
    """A tool definition is invalid or its name is already registered."""


class ToolNotFoundError(KeyError):
    """The requested tool is not registered."""


class ToolValidationError(ValueError):
    """Validation errors with JSON field paths, compatible with ValueError."""

    def __init__(self, errors: list[dict]):
        self.errors = deepcopy(errors)
        super().__init__("; ".join(error["message"] for error in errors))
