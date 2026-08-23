from typing import Protocol, runtime_checkable


@runtime_checkable
class Theme(Protocol):
    """Contract that all theme modules must satisfy.

    A theme module must export a `CSS: str` string containing
    the stylesheet for the CV layout. Optionally, it may also
    export a `THEME_NAME: str` for display purposes.
    """

    CSS: str
