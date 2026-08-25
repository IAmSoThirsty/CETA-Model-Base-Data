from __future__ import annotations

CETA_OPERATION_VOCAB: tuple[str, ...] = (
    "Observe", "ValidateObservation", "AdmitEvidence", "RejectEvidence",
    "CreateClaim", "CreateBelief", "Support", "Contradict", "Undercut",
    "Merge", "Split", "NarrowScope", "ExpandScope", "Verify", "Invalidate",
    "Suspend", "Expire", "Reevaluate", "Adjudicate", "Authorize",
    "RejectAuthorization", "Execute", "Rollback",
)
OPERATION_TO_INDEX={name:i for i,name in enumerate(CETA_OPERATION_VOCAB)}

OBJECT_TYPE_VOCAB=("UNIVERSE","BELIEF","EVIDENCE","CLAIM","OBSERVATION","RULE","GOAL","AUTHORITY","ACTION")
OBJECT_TYPE_TO_INDEX={name:i for i,name in enumerate(OBJECT_TYPE_VOCAB)}

STATUS_VOCAB=(
    "<NONE>","ACTIVE","OBSERVED","VALIDATED","ADMITTED","REJECTED","AUTHORIZED",
    "EXECUTION_REQUESTED","ROLLBACK_REQUESTED","SUSPENDED","INVALIDATED","EXPIRED",
    "LOCKED","PREPARED","CONSUMED","REVOKED","COMPLETED","INDETERMINATE",
)
STATUS_TO_INDEX={name:i for i,name in enumerate(STATUS_VOCAB)}

VERIFICATION_VOCAB=("<NONE>","UNVERIFIED","VERIFIED","INVALID","PENDING_EXTERNAL_VERIFICATION")
VERIFICATION_TO_INDEX={name:i for i,name in enumerate(VERIFICATION_VOCAB)}

EPISTEMIC_STATUS_VOCAB=("<NONE>","OPEN","SUPPORTED","CONTESTED","UNDERCUT")
EPISTEMIC_STATUS_TO_INDEX={name:i for i,name in enumerate(EPISTEMIC_STATUS_VOCAB)}

OPERAND_ROLE_VOCAB=(
    "action_id","adjudication_code","authorization_id","authorization_ref","belief_id","belief_ref",
    "claim_id","claim_ref","compiler_id","consequence","consumer_id","consumer_key_id","evidence_id",
    "evidence_record_id","evidence_ref","evidence_refs","expires_at_epoch_ms","merged_id","nonce",
    "object_ref","object_refs","observation_id","observation_ref","observation_refs","operation","outcome",
    "partitions","payload","payload_hash","permit_id","proposition","reason_code","replacement_id","scope",
    "source_id","source_refs","strategy","subject_id","subject_scope","target_ref","trigger_evidence_refs",
    "trusted_time_evidence_ref","validation_code","validator_id","verification_code",
)
OPERAND_ROLE_TO_INDEX={name:i for i,name in enumerate(OPERAND_ROLE_VOCAB)}

OPERAND_KIND_VOCAB=("REF","REF_LIST","MAPPING","LIST","INT","BOOL","ENUM","OPAQUE_SYMBOL","NULL")
OPERAND_KIND_TO_INDEX={name:i for i,name in enumerate(OPERAND_KIND_VOCAB)}

ENUM_VALUES=frozenset({
    "Execute","Rollback","IDENTICAL_OR_SET_UNION","ACTIVE","SUSPENDED","INVALIDATED",
    "BOUND","STRUCTURE_VALID","SUPPORTED_NO_DEFEATER","CONFLICT_BOUND",
})

FAILURE_HEADS: tuple[str, ...] = (
    "illegal_transition","missing_transition","invariant_violation","provenance_loss",
    "missing_defeaters","improper_scope","illegal_authorization","belief_corruption","replay_mismatch",
)
