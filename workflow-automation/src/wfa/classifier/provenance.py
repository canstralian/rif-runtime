"""Event provenance classification (spec §2.1) — the primary control.

Every event is classified BEFORE any workflow is selected. Classification derives
from authenticated platform metadata (installation ID, actor permission level, ref
protection status) re-fetched from the platform API under the engine's own
credential — never from a self-asserted field in the payload body.

Fail-closed: anything not positively classifiable is ``UNTRUSTED``, never
``TRUSTED`` by default (spec §1.5).
"""

from __future__ import annotations

from typing import Protocol

from wfa.shared.enums import Profile
from wfa.shared.models import Event, ProvenanceFacts


class PlatformClient(Protocol):
    """Authenticated view of platform truth.

    Implementations call the real platform API under the engine credential. The key
    property is that these answers are NOT derived from the event payload body.
    """

    def facts_for(self, event: Event) -> ProvenanceFacts: ...


class Classifier:
    """Assigns a provenance profile and records why (``classification_basis``)."""

    def __init__(self, platform: PlatformClient) -> None:
        self._platform = platform

    def classify(self, event: Event) -> tuple[Profile, str]:
        """Return ``(profile, classification_basis)``.

        The basis string is mandatory in the audit trail (spec §4.8): a run recorded
        as TRUSTED without recording *why* cannot support incident review.
        """

        # Re-fetch authenticated facts. Never trust the payload body for authority.
        try:
            facts = self._platform.facts_for(event)
        except Exception:  # platform unreachable -> cannot positively classify
            return Profile.UNTRUSTED, "platform-unreachable:fail-closed"

        if not facts.installation_verified:
            return Profile.UNTRUSTED, "installation-unverified"

        # --- Positive TRUSTED classifications (spec §2.1) ---
        if facts.scheduled:
            return Profile.TRUSTED, "scheduled-trigger"
        if facts.authenticated_internal:
            return Profile.TRUSTED, "internal-authenticated-channel"
        if event.kind == "push" and facts.ref_protected:
            return Profile.TRUSTED, "push-to-protected-branch"
        if event.kind == "pull_request" and not facts.is_fork_pr and facts.actor_has_write:
            return Profile.TRUSTED, "same-repo-pr-by-write-actor"

        # --- Everything else is UNTRUSTED (spec §2.1) ---
        if event.kind == "pull_request" and facts.is_fork_pr:
            return Profile.UNTRUSTED, "fork-pr"
        if event.kind in ("issues", "issue_comment", "pull_request_review_comment"):
            return Profile.UNTRUSTED, "issue-or-comment"
        if event.kind == "pull_request" and not facts.actor_has_write:
            return Profile.UNTRUSTED, "pr-actor-without-write"
        return Profile.UNTRUSTED, "not-positively-classifiable"
