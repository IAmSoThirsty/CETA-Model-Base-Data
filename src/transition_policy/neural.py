from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import torch
from torch import nn

from ceta import TransitionProposal
from .actions import CetaActionSpaceGenerator
from .encoder import EncodedCandidate, EncodedWorld, StructuredStateEncoder, WorldView
from .schema import (
    CETA_OPERATION_VOCAB, EPISTEMIC_STATUS_TO_INDEX, FAILURE_HEADS, OBJECT_TYPE_TO_INDEX,
    OPERAND_KIND_TO_INDEX, OPERAND_ROLE_TO_INDEX, OPERATION_TO_INDEX, STATUS_TO_INDEX,
    VERIFICATION_TO_INDEX,
)


@dataclass(frozen=True)
class PolicyOutput:
    opcode_logits: torch.Tensor
    candidate_scores: torch.Tensor
    candidate_failure_logits: torch.Tensor
    candidate_proposals: tuple[TransitionProposal, ...]
    rejected_candidate_count: int


class NeuralTransitionPolicy(nn.Module):
    """Candidate-constrained neural CETA transition policy.

    The network never emits text or arbitrary JSON. A target-blind deterministic
    action-space generator enumerates structured CETA proposals from current
    state and explicit external input; the network ranks that action space.
    Runtime-generated identity/proof/output-state fields remain outside this
    model by construction.
    """

    model_id='ceta-neural-transition-policy-v1'
    model_schema_version=3

    def __init__(self, *, hidden_dim: int = 64) -> None:
        super().__init__()
        self.hidden_dim=hidden_dim
        self.encoder=StructuredStateEncoder()
        self.action_space=CetaActionSpaceGenerator()
        self.object_type_emb=nn.Embedding(len(OBJECT_TYPE_TO_INDEX),12)
        self.status_emb=nn.Embedding(len(STATUS_TO_INDEX),10)
        self.verification_emb=nn.Embedding(len(VERIFICATION_TO_INDEX),6)
        self.epistemic_emb=nn.Embedding(len(EPISTEMIC_STATUS_TO_INDEX),6)
        self.node_numeric=nn.Linear(self.encoder.NODE_NUMERIC_DIM,16)
        node_in=12+10+6+6+16
        self.node_project=nn.Sequential(nn.Linear(node_in,hidden_dim),nn.GELU(),nn.LayerNorm(hidden_dim))
        self.global_project=nn.Sequential(nn.Linear(self.encoder.GLOBAL_NUMERIC_DIM,hidden_dim),nn.GELU())
        self.state_project=nn.Sequential(nn.Linear(hidden_dim*3,hidden_dim),nn.GELU(),nn.LayerNorm(hidden_dim))

        self.operation_emb=nn.Embedding(len(CETA_OPERATION_VOCAB),24)
        self.operand_role_emb=nn.Embedding(len(OPERAND_ROLE_TO_INDEX),20)
        self.operand_kind_emb=nn.Embedding(len(OPERAND_KIND_TO_INDEX),10)
        self.operand_numeric=nn.Linear(self.encoder.OPERAND_NUMERIC_DIM,10)
        self.operand_project=nn.Sequential(nn.Linear(20+10+10+hidden_dim,hidden_dim),nn.GELU())
        self.candidate_structural=nn.Linear(self.encoder.CANDIDATE_STRUCTURAL_DIM,12)
        candidate_in=hidden_dim+24+hidden_dim+12
        self.candidate_project=nn.Sequential(nn.Linear(candidate_in,hidden_dim),nn.GELU(),nn.LayerNorm(hidden_dim))
        self.candidate_score=nn.Linear(hidden_dim,1)
        self.failure_head=nn.Linear(hidden_dim,len(FAILURE_HEADS))
        self.opcode_head=nn.Linear(hidden_dim,len(CETA_OPERATION_VOCAB))

    def encode_state(self, encoded: EncodedWorld) -> tuple[torch.Tensor,torch.Tensor]:
        node=torch.cat([
            self.object_type_emb(encoded.node_type),self.status_emb(encoded.node_status),
            self.verification_emb(encoded.node_verification),self.epistemic_emb(encoded.node_epistemic),
            self.node_numeric(encoded.node_numeric),
        ],dim=-1)
        node=self.node_project(node)
        mean=node.mean(dim=0)
        maxv=node.max(dim=0).values
        glob=self.global_project(encoded.global_numeric)
        state=self.state_project(torch.cat([mean,maxv,glob],dim=-1))
        return state,node

    def encode_candidate(self, candidate: EncodedCandidate, state: torch.Tensor, node_embeddings: torch.Tensor) -> torch.Tensor:
        operand_vectors=[]
        for i in range(candidate.operand_role.numel()):
            refs=candidate.operand_ref_indices[i]
            if refs:
                ref_vec=node_embeddings[torch.tensor(refs,dtype=torch.long,device=node_embeddings.device)].mean(dim=0)
            else:
                ref_vec=torch.zeros(self.hidden_dim,dtype=node_embeddings.dtype,device=node_embeddings.device)
            operand_vectors.append(torch.cat([
                self.operand_role_emb(candidate.operand_role[i]),
                self.operand_kind_emb(candidate.operand_kind[i]),
                self.operand_numeric(candidate.operand_numeric[i]),
                ref_vec,
            ],dim=-1))
        operands=self.operand_project(torch.stack(operand_vectors)).mean(dim=0)
        op=self.operation_emb(torch.tensor(candidate.operation_index,dtype=torch.long,device=state.device))
        structural=self.candidate_structural(candidate.structural_numeric)
        return self.candidate_project(torch.cat([state,op,operands,structural],dim=-1))

    def forward_world(self, world: WorldView, *, extra_candidates: Sequence[TransitionProposal]=()) -> PolicyOutput:
        base_candidates=self.action_space.generate(world)
        candidates=base_candidates+tuple(extra_candidates)
        encoded=self.encoder.encode_world(world)
        device=next(self.parameters()).device
        encoded.node_type=encoded.node_type.to(device); encoded.node_status=encoded.node_status.to(device)
        encoded.node_verification=encoded.node_verification.to(device); encoded.node_epistemic=encoded.node_epistemic.to(device)
        encoded.node_numeric=encoded.node_numeric.to(device); encoded.global_numeric=encoded.global_numeric.to(device)
        state,nodes=self.encode_state(encoded)
        opcode_logits=self.opcode_head(state)
        vectors=[]; proposals=[]; rejected=0
        deduped=[]; seen=set()
        for proposal in candidates:
            key=(proposal.input_state_ref,proposal.operation,repr(sorted(proposal.operands.items())))
            if key not in seen:
                seen.add(key); deduped.append(proposal)
        for proposal in deduped:
            try:
                candidate=self.encoder.encode_candidate(proposal,encoded,operation_to_index=OPERATION_TO_INDEX)
            except ValueError:
                rejected += 1
                continue
            candidate.structural_numeric=candidate.structural_numeric.to(device); candidate.operand_role=candidate.operand_role.to(device); candidate.operand_kind=candidate.operand_kind.to(device); candidate.operand_numeric=candidate.operand_numeric.to(device)
            vectors.append(self.encode_candidate(candidate,state,nodes)); proposals.append(proposal)
        if not vectors:
            raise ValueError('no candidate survives constrained CETA decoder')
        matrix=torch.stack(vectors)
        scores=self.candidate_score(matrix).squeeze(-1)
        failures=self.failure_head(matrix)
        return PolicyOutput(opcode_logits,scores,failures,tuple(proposals),rejected)

    @torch.no_grad()
    def propose(self, world: WorldView) -> TransitionProposal:
        self.eval()
        output=self.forward_world(world)
        index=int(torch.argmax(output.candidate_scores).item())
        proposal=output.candidate_proposals[index]
        return TransitionProposal(proposal.input_state_ref,proposal.operation,proposal.operands,self.model_id)
