"""Health / readiness reporting (spec §5.2, §9).

``/readyz`` reports the degradation mode and signature status. Degradation never
silently reclassifies a run to a weaker profile in order to make it runnable — the
mode is surfaced honestly here and in the operator console.
"""

from __future__ import annotations

from dataclasses import dataclass

from wfa.shared.enums import DegradationMode


@dataclass(frozen=True)
class HealthReport:
    mode: DegradationMode
    registry_signature_ok: bool
    engine_signature_ok: bool
    credential_store_reachable: bool
    audit_sink_available: bool

    @property
    def ready(self) -> bool:
        # Minimal mode (registry signature failed) is live but NOT ready.
        return self.mode is not DegradationMode.MINIMAL and self.engine_signature_ok

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode.value,
            "registry_signature_ok": self.registry_signature_ok,
            "engine_signature_ok": self.engine_signature_ok,
            "credential_store_reachable": self.credential_store_reachable,
            "audit_sink_available": self.audit_sink_available,
            "ready": self.ready,
        }


def readiness(
    *,
    registry_signature_ok: bool,
    engine_signature_ok: bool,
    credential_store_reachable: bool,
    audit_sink_available: bool,
) -> HealthReport:
    """Derive the degradation mode from subsystem status (spec §5.2)."""

    if not engine_signature_ok or not registry_signature_ok:
        mode = DegradationMode.MINIMAL
    elif not credential_store_reachable or not audit_sink_available:
        mode = DegradationMode.RESTRICTED
    else:
        mode = DegradationMode.FULL
    return HealthReport(
        mode=mode,
        registry_signature_ok=registry_signature_ok,
        engine_signature_ok=engine_signature_ok,
        credential_store_reachable=credential_store_reachable,
        audit_sink_available=audit_sink_available,
    )
