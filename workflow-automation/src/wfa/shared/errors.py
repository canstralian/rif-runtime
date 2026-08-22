"""Engine exceptions."""

from __future__ import annotations


class WfaError(Exception):
    """Base class for all engine errors."""


class HardBlock(WfaError):
    """A hard-block condition (spec §2.3).

    Carries the ``rule_id`` so the runner can audit the exact rule that fired and
    dead-letter the job. Hard-blocks are never downgraded.
    """

    def __init__(self, rule_id: str, detail: str = "") -> None:
        # Accept either a plain "HB-4" string or a HardBlockRule enum member; store
        # the canonical value ("HB-4"), never the enum's ``ClassName.MEMBER`` repr.
        self.rule_id = str(getattr(rule_id, "value", rule_id))
        self.detail = detail
        super().__init__(f"{self.rule_id}: {detail}" if detail else self.rule_id)


class RegistrationError(WfaError):
    """A workflow failed to register (load-time refusal, spec §1.5).

    Undeclared credentials, missing ``taint``/``permission``/``output_schema``, and
    non-protected sources are refused at load time, never at run time.
    """


class ProfileMismatch(WfaError):
    """A TRUSTED-only workflow was triggered by an UNTRUSTED event (spec §1.5)."""
