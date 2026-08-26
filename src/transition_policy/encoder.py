from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping, Sequence

import torch

from ceta import TransitionProposal
from history import EpistemicObject, ProjectionSnapshot
from .schema import (
    EPISTEMIC_STATUS_TO_INDEX, ENUM_VALUES, OBJECT_TYPE_TO_INDEX, OPERAND_KIND_TO_INDEX,
    OPERAND_ROLE_TO_INDEX, STATUS_TO_INDEX, VERIFICATION_TO_INDEX,
)


@dataclass(frozen=True)
class WorldView:
    snapshot: ProjectionSnapshot
    evidence_view: Mapping[str, Any]
    identity_view: Mapping[str, Any]
    authority_view: Mapping[str, Any]
    proposal_context: Mapping[str, Any]
    now_epoch_ms: int | None


@dataclass
class EncodedWorld:
    object_ids: tuple[str, ...]
    node_type: torch.Tensor
    node_status: torch.Tensor
    node_verification: torch.Tensor
    node_epistemic: torch.Tensor
    node_numeric: torch.Tensor
    global_numeric: torch.Tensor


@dataclass
class EncodedCandidate:
    proposal: TransitionProposal
    operation_index: int
    operand_role: torch.Tensor
    operand_kind: torch.Tensor
    operand_numeric: torch.Tensor
    operand_ref_indices: tuple[tuple[int, ...], ...]


class StructuredStateEncoder:
    """Converts CETA structures to numeric tensors without language tokenization."""

    # The action-space generator and Constitutional VM both consume
    # ``relation_kind`` and the effect operation bound into an AUTHORITY
    # object.  These features must also be visible to the neural state encoder;
    # otherwise Support/Contradict/Undercut and Execute/Rollback collapse onto
    # the same model input even though the runtime can distinguish them.
    NODE_NUMERIC_DIM=13
    GLOBAL_NUMERIC_DIM=16
    OPERAND_NUMERIC_DIM=5

    def encode_world(self, world: WorldView) -> EncodedWorld:
        objects=tuple(sorted(world.snapshot.active_objects,key=lambda x:x.object_id))
        ids=tuple(o.object_id for o in objects)
        types=[]; statuses=[]; verifications=[]; epistemics=[]; numeric=[]
        for obj in objects:
            content=obj.content
            scope=content.get('scope',{}) if isinstance(content.get('scope',{}),Mapping) else {}
            scope_card=sum(len(v) if isinstance(v,list) else 1 for v in scope.values())
            types.append(OBJECT_TYPE_TO_INDEX.get(obj.object_type,0))
            statuses.append(STATUS_TO_INDEX.get(str(content.get('status','<NONE>')),0))
            verifications.append(VERIFICATION_TO_INDEX.get(str(content.get('verification_status','<NONE>')),0))
            epistemics.append(EPISTEMIC_STATUS_TO_INDEX.get(str(content.get('epistemic_status','<NONE>')),0))
            numeric.append([
                float(len(scope)),float(scope_card),float(len(content.get('support_refs',[]) or [])),
                float(len(content.get('contradiction_refs',[]) or [])),float(len(content.get('undercut_refs',[]) or [])),
                float(isinstance(content.get('expires_at_epoch_ms'),int)),float(obj.object_type=='AUTHORITY'),float(obj.object_type=='ACTION'),
                float(content.get('relation_kind')=='Support'),float(content.get('relation_kind')=='Contradict'),
                float(content.get('relation_kind')=='Undercut'),
                float(obj.object_type=='AUTHORITY' and content.get('operation')=='Execute'),
                float(obj.object_type=='AUTHORITY' and content.get('operation')=='Rollback'),
            ])
        if not objects:
            # A zero node is padding only. It carries no object identity and cannot
            # be referenced by a candidate pointer.
            types=[0]; statuses=[0]; verifications=[0]; epistemics=[0]; numeric=[[0.0]*self.NODE_NUMERIC_DIM]

        ev_status=[str(v.get('status','')) for v in world.evidence_view.values() if isinstance(v,Mapping)]
        id_status=[str(v.get('status','')) for v in world.identity_view.values() if isinstance(v,Mapping)]
        caps=set(world.authority_view.get('authorized_capabilities',[]) if isinstance(world.authority_view,Mapping) else [])
        permits=world.authority_view.get('permits',{}) if isinstance(world.authority_view,Mapping) else {}
        permit_status=[str(v.get('status','')) for v in permits.values() if isinstance(v,Mapping)]
        context=world.proposal_context if isinstance(world.proposal_context,Mapping) else {}
        global_numeric=torch.tensor([
            float(len(objects)),float(ev_status.count('VALIDATED')),float(ev_status.count('REJECTED')),
            float(id_status.count('VERIFIED')),float(id_status.count('REJECTED')),
            float('scope_expand' in caps),float('adjudicate' in caps),float('authorize' in caps),
            float(permit_status.count('ISSUED')),float(permit_status.count('PREPARED')),float(permit_status.count('CONSUMED')),
            float(world.now_epoch_ms is not None),
            float(len(context.get('incoming_observations',[]) or [])),
            float(len(context.get('claim_material',[]) or [])),
            float(len(context.get('authorization_requests',[]) or [])),
            float(len(context.get('authorization_rejections',[]) or [])),
        ],dtype=torch.float32)
        return EncodedWorld(
            object_ids=ids,
            node_type=torch.tensor(types,dtype=torch.long),
            node_status=torch.tensor(statuses,dtype=torch.long),
            node_verification=torch.tensor(verifications,dtype=torch.long),
            node_epistemic=torch.tensor(epistemics,dtype=torch.long),
            node_numeric=torch.tensor(numeric,dtype=torch.float32),
            global_numeric=global_numeric,
        )

    def encode_candidate(self, proposal: TransitionProposal, encoded_world: EncodedWorld, *, operation_to_index: Mapping[str,int]) -> EncodedCandidate:
        if proposal.operation not in operation_to_index:
            raise ValueError(f'candidate opcode is outside constrained CETA vocabulary: {proposal.operation}')
        object_index={object_id:i for i,object_id in enumerate(encoded_world.object_ids)}
        roles=[]; kinds=[]; numeric=[]; refs=[]
        for role,value in sorted(proposal.operands.items()):
            if role not in OPERAND_ROLE_TO_INDEX:
                raise ValueError(f'operand role is outside constrained CETA vocabulary: {role}')
            kind,ref_indices,features=self._operand_features(value,object_index)
            roles.append(OPERAND_ROLE_TO_INDEX[role]); kinds.append(OPERAND_KIND_TO_INDEX[kind]); numeric.append(features); refs.append(ref_indices)
        if not roles:
            roles=[0]; kinds=[OPERAND_KIND_TO_INDEX['NULL']]; numeric=[[0.0]*self.OPERAND_NUMERIC_DIM]; refs=[()]
        return EncodedCandidate(
            proposal=proposal,
            operation_index=operation_to_index[proposal.operation],
            operand_role=torch.tensor(roles,dtype=torch.long),
            operand_kind=torch.tensor(kinds,dtype=torch.long),
            operand_numeric=torch.tensor(numeric,dtype=torch.float32),
            operand_ref_indices=tuple(refs),
        )

    def _operand_features(self, value: Any, object_index: Mapping[str,int]) -> tuple[str,tuple[int,...],list[float]]:
        refs: tuple[int,...]=()
        list_len=0; mapping_size=0; numeric_value=0.0; is_existing_ref=0.0; is_enum=0.0
        if isinstance(value,str):
            if value in object_index:
                kind='REF'; refs=(object_index[value],); is_existing_ref=1.0
            elif value in ENUM_VALUES:
                kind='ENUM'; is_enum=1.0
            else:
                kind='OPAQUE_SYMBOL'
        elif isinstance(value,list):
            list_len=len(value)
            matched=tuple(object_index[x] for x in value if isinstance(x,str) and x in object_index)
            if matched and len(matched)==len(value): kind='REF_LIST'; refs=matched; is_existing_ref=1.0
            else: kind='LIST'
        elif isinstance(value,Mapping):
            kind='MAPPING'; mapping_size=len(value)
        elif isinstance(value,bool): kind='BOOL'; numeric_value=float(value)
        elif isinstance(value,int): kind='INT'; numeric_value=float(max(-1_000_000,min(1_000_000,value)))/1_000_000.0
        elif value is None: kind='NULL'
        else: kind='OPAQUE_SYMBOL'
        return kind,refs,[float(list_len),float(mapping_size),numeric_value,is_existing_ref,is_enum]


def world_from_training_case(case: Any) -> WorldView:
    data=json.loads(case.state_json)
    snapshot=ProjectionSnapshot(
        state_ref=data['state_ref'],
        active_objects=tuple(EpistemicObject.from_dict(x) for x in data['active_objects']),
        supersessions=tuple(),
    )
    if data.get('supersessions'):
        from history import Supersession
        snapshot=ProjectionSnapshot(snapshot.state_ref,snapshot.active_objects,tuple(Supersession(**x) for x in data['supersessions']))
    return WorldView(
        snapshot=snapshot,
        evidence_view=json.loads(case.evidence_view_json),
        identity_view=json.loads(case.identity_view_json),
        authority_view=json.loads(case.authority_view_json),
        proposal_context=json.loads(case.proposal_context_json),
        now_epoch_ms=case.now_epoch_ms,
    )
