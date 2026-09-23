"""Example business stage names for the case-lifecycle ledger tests.

These names are deliberately kept out of ``twinbox_core/``: the engine holds no
business stage vocabulary, so any stage set that appears in a fixture is a
signal the engine has leaked a domain term.  The test module asserts none of
these appear anywhere under ``twinbox_core/``.
"""

CASE_STAGE_NAMES = [
    "service_kickoff",
    "requirement_gathering",
    "proposal_drafting",
    "internal_review_gate",
    "customer_signoff",
    "delivery_execution",
    "production_release",
    "post_launch_monitor",
    "support_escalation",
    "billing_resolution",
]
