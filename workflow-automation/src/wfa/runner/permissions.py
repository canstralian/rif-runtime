"""Permission intersection: profile ∩ definition (spec §3.4, §6.1).

The profile OUTRANKS the workflow definition. A TRUSTED-only step in a workflow
running under UNTRUSTED does not execute, regardless of what the definition says.
Permissions never widen at runtime.
"""

from __future__ import annotations

from wfa.shared.enums import Profile


def intersect_permissions(
    profile: Profile,
    declared_permissions: list[str],
    untrusted_read_permissions: list[str],
) -> frozenset[str]:
    """Compute the effective permission set for a run.

    * TRUSTED: the full set the definition declares.
    * UNTRUSTED: only declared permissions that are also on the read-only allow-list
      (spec §2.1 "no egress except to the allow-listed read APIs"). Never SINK, never
      credentials — enforced separately in the engine, but the permission floor is
      here.
    * Anything else (UNSPECIFIED): empty set (fail-closed).
    """

    declared = set(declared_permissions)
    if profile is Profile.TRUSTED:
        return frozenset(declared)
    if profile is Profile.UNTRUSTED:
        return frozenset(declared & set(untrusted_read_permissions))
    return frozenset()


def credential_scope(profile: Profile, declared_credentials: list[str]) -> frozenset[str]:
    """The credentials a run may use. UNTRUSTED gets zero (spec §4.5, HB-4)."""

    if profile is Profile.TRUSTED:
        return frozenset(declared_credentials)
    return frozenset()
