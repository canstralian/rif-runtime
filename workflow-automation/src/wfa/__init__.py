"""WFA-001 — Workflow Automation.

An event-driven, unattended developer automation engine. The security model rests
on provenance classification and pre-committed policy (see the WFA-001 spec), not
on approval prompts, because at execution time nobody is watching.

Constitutional invariants (spec §1, §2, §4, §7) are enforced structurally by the
modules under this package; the runner (`wfa.runner.engine`) is the single
enforcement chokepoint through which every step dispatch passes.
"""

__version__ = "0.1.0"
