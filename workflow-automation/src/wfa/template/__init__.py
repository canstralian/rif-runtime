"""Templating: value substitution with no executable semantics (spec §2.6)."""

from wfa.template.substitute import (
    TemplateError,
    resolve_args,
    substitute,
)

__all__ = ["TemplateError", "resolve_args", "substitute"]
