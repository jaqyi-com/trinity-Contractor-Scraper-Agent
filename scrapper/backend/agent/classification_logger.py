# classification_logger.py
# Writes a row to `classification_log` for EVERY decision (INCLUDED + EXCLUDED).
# Per PDF Section 7 — "Run log showing rows in/out per stage and reject reasons".

from agent.schema import GoogleSeed, ClassificationDecision
from agent.db import insert_classification_log


def log_decision(
    job_id: str,
    seed: GoogleSeed,
    decision: ClassificationDecision,
) -> None:
    """Persist classification decision to audit log."""
    insert_classification_log({
        "job_id": job_id,
        "business_name": seed.business_name,
        "place_id": seed.place_id,
        "decision": decision.decision,
        "assigned_tier": decision.assigned_tier,
        "matched_keywords": [m.model_dump() for m in decision.matched_keywords],
        "exclusion_keywords": [m.model_dump() for m in decision.exclusion_keywords],
        "classifier_text": decision.classifier_text,
        "reason": decision.reason,
    })
