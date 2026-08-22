"""Credential handling (spec §4.5).

Credentials are held encrypted at rest (envelope encryption; a KMS-backed data key
is modelled here with Fernet standing in for the KMS-decrypted data key), decrypted
into process memory only for the duration of a step, and scoped per workflow at
registration — a workflow declares the credentials it may use and receives no
others.

The load-bearing invariant: an **UNTRUSTED-profile run receives no credentials at
all** (HB-4), not a reduced set. Zero is verifiable by inspection — the runner never
constructs a ``CredentialResolver`` for an UNTRUSTED run, and even if one is
constructed defensively, ``CredentialResolver`` refuses when its profile is not
TRUSTED.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from wfa.shared.enums import Profile
from wfa.shared.errors import HardBlock
from wfa.shared.rules import HardBlockRule


def _data_key_from(master: bytes) -> bytes:
    """Derive a URL-safe 32-byte Fernet key from an arbitrary master secret.

    In production the data key comes from KMS ``GenerateDataKey``; here we derive one
    deterministically so tests need no external KMS.
    """

    return base64.urlsafe_b64encode(hashlib.sha256(master).digest())


class CredentialBroker:
    """Envelope-encrypted credential store with per-workflow scoping."""

    def __init__(self, master_secret: bytes) -> None:
        self._fernet = Fernet(_data_key_from(master_secret))
        # ciphertext keyed by (workflow_id, credential_ref)
        self._store: dict[tuple[str, str], bytes] = {}
        self._reachable = True

    def register(self, workflow_id: str, credential_ref: str, secret_value: str) -> None:
        self._store[(workflow_id, credential_ref)] = self._fernet.encrypt(secret_value.encode())

    def set_reachable(self, reachable: bool) -> None:
        """Toggle store availability (spec §5.1 credential-store-unavailable)."""

        self._reachable = reachable

    @property
    def reachable(self) -> bool:
        return self._reachable

    def _decrypt(self, workflow_id: str, credential_ref: str) -> str:
        if not self._reachable:
            # Credential store unreachable: credentialed steps refuse (spec §1.5).
            raise HardBlock(HardBlockRule.HB_4, "credential store unreachable")
        ciphertext = self._store.get((workflow_id, credential_ref))
        if ciphertext is None:
            raise HardBlock(HardBlockRule.HB_4, f"undeclared credential {credential_ref!r}")
        try:
            return self._fernet.decrypt(ciphertext).decode()
        except InvalidToken as exc:  # pragma: no cover - integrity failure
            raise HardBlock(HardBlockRule.HB_8, "credential integrity failure") from exc

    def resolver_for(
        self, workflow_id: str, profile: Profile, credential_scope: frozenset[str]
    ) -> "CredentialResolver | DeniedCredentials":
        """Build a scoped resolver for a run, or a denying stub for UNTRUSTED.

        UNTRUSTED never gets a real resolver. Returning ``DeniedCredentials`` (rather
        than ``None``) means even a step that ignores the engine's pre-check and calls
        ``ctx.credentials.get(...)`` is hard-blocked (HB-4) — zero credentials,
        verifiable by inspection.
        """

        if profile is not Profile.TRUSTED:
            return DeniedCredentials()
        return CredentialResolver(self, workflow_id, profile, credential_scope)


class DeniedCredentials:
    """A credential handle that refuses every read (HB-4). Used for non-TRUSTED runs."""

    def get(self, credential_ref: str) -> str:
        raise HardBlock(HardBlockRule.HB_4, "no credentials available to a non-TRUSTED run")


class CredentialResolver:
    """Per-run, per-workflow credential handle passed into a step context.

    Enforces, at read time:
      * profile must be TRUSTED (HB-4) — defence in depth on top of the broker only
        building resolvers for TRUSTED runs;
      * the requested ref must be within the workflow's declared scope.
    """

    def __init__(
        self,
        broker: CredentialBroker,
        workflow_id: str,
        profile: Profile,
        scope: frozenset[str],
    ) -> None:
        self._broker = broker
        self._workflow_id = workflow_id
        self._profile = profile
        self._scope = scope

    def get(self, credential_ref: str) -> str:
        if self._profile is not Profile.TRUSTED:
            raise HardBlock(HardBlockRule.HB_4, "credential requested by non-TRUSTED run")
        if credential_ref not in self._scope:
            raise HardBlock(HardBlockRule.HB_4, f"credential {credential_ref!r} out of scope")
        return self._broker._decrypt(self._workflow_id, credential_ref)
