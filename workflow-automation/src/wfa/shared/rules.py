"""Hard-block rule identifiers (spec §2.3).

A hard-block aborts the run, emits an audit record naming the rule ID, and
dead-letters the job. They are never downgraded.
"""

from __future__ import annotations

from enum import Enum


class HardBlockRule(str, Enum):
    HB_1 = "HB-1"  # Webhook HMAC verification fails
    HB_2 = "HB-2"  # Replay window / delivery_id already consumed
    HB_3 = "HB-3"  # Workflow definition sourced from a non-protected ref
    HB_4 = "HB-4"  # Credential requested by an UNTRUSTED-profile run
    HB_5 = "HB-5"  # T4 content reaching a shell/SQL/executable-template sink
    HB_6 = "HB-6"  # Egress host outside the T2 allow-list
    HB_7 = "HB-7"  # max_chain_depth exceeded
    HB_8 = "HB-8"  # Engine/registry signature verification failure
    HB_9 = "HB-9"  # Step permission not present in the run's profile


RULE_DESCRIPTIONS: dict[str, str] = {
    HardBlockRule.HB_1: "Webhook HMAC verification fails",
    HardBlockRule.HB_2: "Delivery timestamp outside the replay window or delivery_id consumed",
    HardBlockRule.HB_3: "Workflow definition sourced from a non-protected ref",
    HardBlockRule.HB_4: "Credential requested by an UNTRUSTED-profile run",
    HardBlockRule.HB_5: "T4 content reaching a shell, SQL, or executable-template sink",
    HardBlockRule.HB_6: "Egress host outside the T2 allow-list",
    HardBlockRule.HB_7: "max_chain_depth exceeded",
    HardBlockRule.HB_8: "Engine signature config or registry signature verification failure",
    HardBlockRule.HB_9: "Step permission not present in the run's profile",
}

# Non-hard-block audit reasons that still abort/refuse a run.
PROFILE_MISMATCH = "PROFILE_MISMATCH"
SINK_NOT_PERMITTED = "SINK_NOT_PERMITTED"  # SINK step under a non-TRUSTED profile
ESCALATION_REQUIRED = "ESCALATION_REQUIRED"  # escalated step lacked valid T3 approval
AUDIT_UNAVAILABLE = "AUDIT_UNAVAILABLE"  # SINK/escalated refused, audit sink down
TAINT_MISMATCH = "TAINT_MISMATCH"  # declared taint != step-type intrinsic taint
