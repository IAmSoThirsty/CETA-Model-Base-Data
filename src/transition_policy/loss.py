from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import torch
import torch.nn.functional as F

from ceta import ConstitutionalVM, VmDisposition
from .encoder import world_from_training_case
from .neural import PolicyOutput
from .schema import CETA_OPERATION_VOCAB, FAILURE_HEADS, OPERATION_TO_INDEX


@dataclass(frozen=True)
class CetaLossWeights:
    operation_selection: float = 1.0
    transition_rank: float = 2.0
    failure_surface: float = 1.0


@dataclass
class CetaLossResult:
    total: torch.Tensor
    operation_selection_loss: torch.Tensor
    transition_rank_loss: torch.Tensor
    failure_surface_loss: torch.Tensor


_TAG_TO_HEAD={
    'replay_fault':'replay_mismatch',
    'provenance_corruption':'provenance_loss',
    'provenance_loss':'provenance_loss',
    'missing_defeaters':'missing_defeaters',
    'improper_scope':'improper_scope',
    'illegal_authorization':'illegal_authorization',
    'authority_failure':'illegal_authorization',
    'belief_corruption':'belief_corruption',
    'invariant_violation':'invariant_violation',
    'structural_output_failure':'invariant_violation',
    'objective_substitution_failure':'illegal_authorization',
}


def failure_labels(case: Any, output: PolicyOutput) -> torch.Tensor:
    """Label candidate failure surfaces with the VM as the legality oracle.

    Non-target candidates are not assumed illegal. A different transition may
    be legal but still not be the curriculum's intended next transition; that
    receives only the missing-transition/ranking label. Explicit adversarial
    negatives add their historical failure tags on top of the VM disposition.
    """
    explicit={_proposal_json(alt.proposal):alt for alt in case.illegal_alternatives}
    target_json=_proposal_json(case.target_proposal)
    world=world_from_training_case(case)
    vm=ConstitutionalVM()
    rows=[]
    for proposal in output.candidate_proposals:
        row={name:0.0 for name in FAILURE_HEADS}
        proposal_json=_proposal_json(proposal)
        if proposal_json != target_json:
            row['missing_transition']=1.0
            decision=vm.evaluate(
                proposal,projected_snapshot=world.snapshot,admitted_evidence_view=world.evidence_view,
                identity_view=world.identity_view,authority_snapshot=world.authority_view,
                now_epoch_ms=world.now_epoch_ms,constitutional_epoch='training-label-oracle',
            )
            if decision.disposition is not VmDisposition.LEGAL:
                row['illegal_transition']=1.0
                if decision.disposition is VmDisposition.HALT:
                    row['invariant_violation']=1.0
            alt=explicit.get(proposal_json)
            if alt:
                for tag in alt.failure_tags:
                    head=_TAG_TO_HEAD.get(tag)
                    if head:
                        row[head]=1.0
        rows.append([row[name] for name in FAILURE_HEADS])
    return torch.tensor(rows,dtype=torch.float32,device=output.candidate_failure_logits.device)


def operation_selection_logits(output: PolicyOutput) -> torch.Tensor:
    """Return the best deployed candidate score for each CETA operation."""
    logits=[]
    for operation in CETA_OPERATION_VOCAB:
        indices=[i for i,proposal in enumerate(output.candidate_proposals) if proposal.operation==operation]
        if indices:
            index=torch.tensor(indices,dtype=torch.long,device=output.candidate_scores.device)
            logits.append(torch.max(output.candidate_scores.index_select(0,index),dim=0).values)
        else:
            logits.append(output.candidate_scores.new_tensor(float('-inf')))
    return torch.stack(logits)


def compute_ceta_loss(case: Any, output: PolicyOutput, *, weights: CetaLossWeights=CetaLossWeights()) -> CetaLossResult:
    target_op=torch.tensor([OPERATION_TO_INDEX[case.target_proposal.operation]],dtype=torch.long,device=output.candidate_scores.device)
    operation_selection_loss=F.cross_entropy(operation_selection_logits(output).unsqueeze(0),target_op)
    target_index=None
    target_json=_proposal_json(case.target_proposal)
    for i,p in enumerate(output.candidate_proposals):
        if _proposal_json(p)==target_json:
            target_index=i
            break
    if target_index is None:
        raise ValueError('target proposal is not recoverable from the target-blind CETA action space')
    transition_rank_loss=F.cross_entropy(output.candidate_scores.unsqueeze(0),torch.tensor([target_index],dtype=torch.long,device=output.candidate_scores.device))
    labels=failure_labels(case,output)
    failure_surface_loss=F.binary_cross_entropy_with_logits(output.candidate_failure_logits,labels)
    total=(
        weights.operation_selection*operation_selection_loss
        + weights.transition_rank*transition_rank_loss
        + weights.failure_surface*failure_surface_loss
    )
    return CetaLossResult(total,operation_selection_loss,transition_rank_loss,failure_surface_loss)


def candidate_sequence(case: Any) -> tuple:
    """Training/evaluation adversarial candidates; never inserts the target label."""
    return tuple(alt.proposal for alt in case.illegal_alternatives)


def _proposal_json(proposal) -> str:
    import json
    return json.dumps({'input_state_ref':proposal.input_state_ref,'operation':proposal.operation,'operands':dict(proposal.operands),'proposer_id':proposal.proposer_id},sort_keys=True,separators=(',',':'))
