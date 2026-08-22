"""Security layer (spec §4).

Every emitter's write path goes through ``redactor``; every value bound for a
downstream sink goes through ``encode``; every egress goes through ``egress``; every
action is recorded by ``audit``.
"""

from wfa.security.audit import AuditLog
from wfa.security.credentials import (
    CredentialBroker,
    CredentialResolver,
    DeniedCredentials,
)
from wfa.security.egress import EgressGuard
from wfa.security.encode import encode_for_sink
from wfa.security.normalize import normalize_text, normalize_tree
from wfa.security.redactor import Redactor

__all__ = [
    "AuditLog",
    "CredentialBroker",
    "CredentialResolver",
    "DeniedCredentials",
    "EgressGuard",
    "encode_for_sink",
    "normalize_text",
    "normalize_tree",
    "Redactor",
]
