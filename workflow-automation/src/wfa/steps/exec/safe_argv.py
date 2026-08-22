"""Argv-array execution with no shell (spec §4.2).

Any subprocess step receives a fixed program and an argument array. There is no
shell, no ``shell=True``, and no string concatenation into a command line. T4 values
are placed into individual argv elements verbatim.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class CommandSpec:
    program: str
    fixed_args: tuple[str, ...] = ()


def build_argv(spec: CommandSpec, data_args: list[str]) -> list[str]:
    """Assemble the final argv: fixed program + fixed args + T4 data args.

    Every element of ``data_args`` becomes exactly one argv element. No element is
    ever split, globbed, or interpreted; ``$(...)``, backticks, ``|``, ``;`` and
    newlines inside a data arg are literal characters of that single argument.
    """

    argv = [spec.program, *spec.fixed_args]
    for a in data_args:
        argv.append(str(a))
    return argv


def run_argv(argv: list[str], timeout_s: float = 30.0) -> subprocess.CompletedProcess[str]:
    """Execute ``argv`` directly (never via a shell). ``shell`` is hard-coded False."""

    return subprocess.run(  # noqa: S603 - argv array, shell disabled by construction
        argv,
        shell=False,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )
