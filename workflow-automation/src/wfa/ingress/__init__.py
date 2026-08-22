"""Ingress layer: webhook endpoints, HMAC verify, replay window, size bound.

No parsing happens before authentication (spec §8.1): the raw body is HMAC-verified
first, so parser vulnerabilities are unreachable pre-authentication.
"""

from wfa.ingress.hmac_verify import HmacVerifier, verify_signature
from wfa.ingress.replay import ReplayResult, ReplayWindow
from wfa.ingress.server import IngressResult, WebhookIngress

__all__ = [
    "HmacVerifier",
    "verify_signature",
    "ReplayResult",
    "ReplayWindow",
    "IngressResult",
    "WebhookIngress",
]
