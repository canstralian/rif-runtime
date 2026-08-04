from rif_runtime.governance.drift import DriftVector, recommend_correction
from rif_runtime.schemas import PolicyRequest, Posture


class OrchestratorAgent:
    name = "agent:orchestrator"

    def request_http(self, target: str, reason: str | None = None) -> PolicyRequest:
        return PolicyRequest(
            actor=self.name,
            action="http.request",
            target=target,
            reason=reason,
        )

    def _choose_correction(self, drift_vector: DriftVector) -> Posture:
        return recommend_correction(drift_vector)

    def choose_correction(self, drift_vector: DriftVector) -> Posture:
        return self._choose_correction(drift_vector)
