"""Minimal module entrypoint (``python -m wfa``).

The container image (``deploy/Dockerfile``) runs this with a role argument
(``ingress`` or ``worker``). Wiring the concrete ingress HTTP server and worker loop
to a real broker/credential store is a deployment concern (spec OD-1); this
entrypoint validates the role and reports version/health so the image has a working,
non-crashing default.
"""

from __future__ import annotations

import json
import sys

from wfa import __version__

_ROLES = {"ingress", "worker"}


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    role = args[0] if args else "help"
    if role in _ROLES:
        print(json.dumps({"wfa": __version__, "role": role, "status": "starting"}))
        return 0
    print(json.dumps({"wfa": __version__, "usage": "python -m wfa {ingress|worker}"}))
    return 0 if role == "help" else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
