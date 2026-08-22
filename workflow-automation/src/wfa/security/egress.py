"""Egress control (spec §2.3 HB-6, §9).

Egress is permitted only to hosts on the T2 allow-list. RFC1918, loopback, and
link-local ranges are blocked outright — the last of these closes cloud
metadata-service access (169.254.169.254), a standard pivot from any step accepting
a URL.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

from wfa.shared.errors import HardBlock
from wfa.shared.rules import HardBlockRule


class EgressGuard:
    def __init__(self, allow_list: list[str]) -> None:
        # Store hosts lower-cased; exact host match only (no suffix wildcards here).
        self._allow = {h.strip().lower() for h in allow_list if h.strip()}

    @staticmethod
    def _is_blocked_ip(host: str) -> bool:
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            return False
        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        )

    def check(self, url: str) -> str:
        """Return the host if egress is allowed; raise ``HardBlock`` (HB-6) otherwise."""

        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if not host:
            raise HardBlock(HardBlockRule.HB_6, f"no host in url {url!r}")
        # Block raw IP literals in private/loopback/link-local ranges regardless of
        # the allow-list (defence against metadata-service pivots).
        if self._is_blocked_ip(host):
            raise HardBlock(HardBlockRule.HB_6, f"blocked ip range: {host}")
        if host not in self._allow:
            raise HardBlock(HardBlockRule.HB_6, f"host not in allow-list: {host}")
        return host

    def allows(self, url: str) -> bool:
        try:
            self.check(url)
            return True
        except HardBlock:
            return False
