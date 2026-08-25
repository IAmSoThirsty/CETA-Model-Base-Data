from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import torch

from ceta import ConstitutionalVM, VmDisposition
from history import canonical_json, domain_hash
from transition_policy import NeuralTransitionPolicy, candidate_sequence, compute_ceta_loss, world_from_training_case
from .model import TransitionTrainingCase


class TrainingBindingError(RuntimeError):
    pass


@dataclass(frozen=True)
class TrainingConfig:
    seed: int = 1701
    learning_rate: float = 0.002
    weight_decay: float = 0.0
    hidden_dim: int = 64
    gradient_clip_norm: float = 1.0

    def to_dict(self) -> dict[str,Any]:
        return asdict(self)

    @property
    def config_hash(self) -> str:
        return domain_hash(self.to_dict(),domain='CETA/TRAINING_CONFIG/v1')


@dataclass(frozen=True)
class TrainingCursor:
    run_id: str
    epoch_index: int
    next_case_offset: int
    global_step: int
    dataset_sha256: str
    split: str
    config_hash: str
    curriculum_manifest_sha256: str
    curriculum_splits_sha256: str
    curriculum_generator_id: str

    def to_dict(self) -> dict[str,Any]: return asdict(self)


@dataclass(frozen=True)
class CurriculumBinding:
    manifest_sha256: str
    splits_sha256: str
    generator_id: str

    def to_dict(self) -> dict[str,Any]:
        return asdict(self)


@dataclass(frozen=True)
class CheckpointRef:
    path: str
    sha256: str
    model_hash: str
    optimizer_hash: str
    cursor: TrainingCursor

    def to_dict(self) -> dict[str,Any]:
        return {'path':Path(self.path).name,'sha256':self.sha256,'model_hash':self.model_hash,'optimizer_hash':self.optimizer_hash,'cursor':self.cursor.to_dict()}


@dataclass(frozen=True)
class EvaluationMetrics:
    split: str
    case_count: int
    target_accuracy: float
    opcode_accuracy: float
    legal_selection_rate: float
    mean_transition_loss: float
    rejected_candidate_count: int
    checkpoint_sha256: str
    dataset_sha256: str
    curriculum_manifest_sha256: str
    curriculum_splits_sha256: str
    evaluation_hash: str

    def body(self) -> dict[str,Any]:
        return {
            'split':self.split,'case_count':self.case_count,'target_accuracy':self.target_accuracy,
            'opcode_accuracy':self.opcode_accuracy,'legal_selection_rate':self.legal_selection_rate,
            'mean_transition_loss':self.mean_transition_loss,'rejected_candidate_count':self.rejected_candidate_count,
            'checkpoint_sha256':self.checkpoint_sha256,'dataset_sha256':self.dataset_sha256,
            'curriculum_manifest_sha256':self.curriculum_manifest_sha256,'curriculum_splits_sha256':self.curriculum_splits_sha256,
        }


@dataclass(frozen=True)
class PromotionPolicy:
    min_target_accuracy: float
    min_opcode_accuracy: float
    min_legal_selection_rate: float
    max_mean_transition_loss: float

    def __post_init__(self) -> None:
        for name in ('min_target_accuracy','min_opcode_accuracy','min_legal_selection_rate'):
            value=getattr(self,name)
            if not 0.0 <= value <= 1.0: raise TrainingBindingError(f'{name} must be in [0,1]')
        if self.max_mean_transition_loss < 0: raise TrainingBindingError('max_mean_transition_loss must be nonnegative')

    def evaluate(self, metrics: EvaluationMetrics) -> tuple[bool,tuple[str,...]]:
        failures=[]
        if metrics.target_accuracy < self.min_target_accuracy: failures.append('TARGET_ACCURACY_FLOOR')
        if metrics.opcode_accuracy < self.min_opcode_accuracy: failures.append('OPCODE_ACCURACY_FLOOR')
        if metrics.legal_selection_rate < self.min_legal_selection_rate: failures.append('LEGAL_SELECTION_FLOOR')
        if metrics.mean_transition_loss > self.max_mean_transition_loss: failures.append('TRANSITION_LOSS_CEILING')
        return (not failures,tuple(failures))


class TrainingEventLedger:
    """Append-only hash-chained training lifecycle evidence."""
    GENESIS='sha256:'+'0'*64

    def __init__(self,path: str|Path) -> None:
        self.path=Path(path); self._events=[]
        if self.path.exists(): self._load()

    @property
    def current_root(self) -> str:
        return self._events[-1]['event_hash'] if self._events else self.GENESIS

    @property
    def events(self) -> tuple[dict[str,Any],...]: return tuple(dict(x) for x in self._events)

    def append(self,event_type: str,payload: Mapping[str,Any]) -> dict[str,Any]:
        body={'sequence':len(self._events)+1,'event_type':event_type,'payload':dict(payload),'previous_hash':self.current_root}
        event={**body,'event_hash':domain_hash(body,domain='CETA/TRAINING_EVENT/v1')}
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.path.open('a',encoding='utf-8',newline='\n') as handle:
            handle.write(canonical_json(event)+'\n'); handle.flush(); os.fsync(handle.fileno())
        self._events.append(event)
        return event

    def verify(self) -> bool:
        previous=self.GENESIS
        for i,event in enumerate(self._events,1):
            if event['sequence']!=i or event['previous_hash']!=previous: raise TrainingBindingError('training event chain ordering mismatch')
            body={k:event[k] for k in ('sequence','event_type','payload','previous_hash')}
            if event['event_hash']!=domain_hash(body,domain='CETA/TRAINING_EVENT/v1'): raise TrainingBindingError('training event hash mismatch')
            previous=event['event_hash']
        return True

    def _load(self) -> None:
        events=[]
        with self.path.open(encoding='utf-8') as handle:
            for lineno,line in enumerate(handle,1):
                if not line.strip(): continue
                try: event=json.loads(line)
                except Exception as exc: raise TrainingBindingError(f'invalid training event line {lineno}: {exc}') from exc
                events.append(event)
        self._events=events; self.verify()


class CheckpointStore:
    def __init__(self,root: str|Path) -> None:
        self.root=Path(root); self.root.mkdir(parents=True,exist_ok=True)

    def save(self,*,model: NeuralTransitionPolicy,optimizer: torch.optim.Optimizer,cursor: TrainingCursor,config: TrainingConfig) -> CheckpointRef:
        model_hash=hash_torch_state(model.state_dict(),domain='CETA/MODEL_STATE/v1')
        optimizer_hash=hash_torch_state(optimizer.state_dict(),domain='CETA/OPTIMIZER_STATE/v1')
        payload={
            'schema_version':1,'model_class':'NeuralTransitionPolicy','model_hidden_dim':model.hidden_dim,
            'model_state':model.state_dict(),'optimizer_state':optimizer.state_dict(),
            'cursor':cursor.to_dict(),'config':config.to_dict(),'model_hash':model_hash,'optimizer_hash':optimizer_hash,
        }
        name=f"checkpoint-e{cursor.epoch_index:04d}-s{cursor.global_step:08d}-o{cursor.next_case_offset:06d}.pt"
        path=self.root/name; temp=self.root/(name+'.tmp')
        with temp.open('wb') as handle:
            torch.save(payload,handle); handle.flush(); os.fsync(handle.fileno())
        os.replace(temp,path); _fsync_dir(self.root)
        digest=file_sha256(path)
        sidecar=path.with_suffix(path.suffix+'.json')
        sidecar_body={'schema_version':1,'checkpoint':path.name,'sha256':digest,'model_hash':model_hash,'optimizer_hash':optimizer_hash,'cursor':cursor.to_dict(),'config_hash':config.config_hash}
        _atomic_json(sidecar,sidecar_body)
        return CheckpointRef(str(path),digest,model_hash,optimizer_hash,cursor)

    def load_committed(self,checkpoint_record: Mapping[str,Any],*,expected_dataset_sha256: str,expected_config: TrainingConfig,expected_binding: CurriculumBinding,device: str|torch.device='cpu') -> tuple[NeuralTransitionPolicy,torch.optim.Optimizer,CheckpointRef]:
        recorded_path=Path(str(checkpoint_record.get("path","")))
        if not recorded_path.name:
            raise TrainingBindingError("committed checkpoint record has no path")
        path=self.root/recorded_path.name
        sidecar=path.with_suffix(path.suffix+".json")
        expected_sha=str(checkpoint_record.get("sha256",""))
        if not path.is_file() or file_sha256(path)!=expected_sha:
            raise TrainingBindingError("committed checkpoint hash mismatch")
        if not sidecar.is_file():
            raise TrainingBindingError("committed checkpoint sidecar missing")
        meta=json.loads(sidecar.read_text(encoding="utf-8"))
        if meta.get("checkpoint")!=path.name or meta.get("sha256")!=expected_sha:
            raise TrainingBindingError("checkpoint sidecar binding mismatch")
        payload=torch.load(path,map_location="cpu",weights_only=True)
        if payload.get("schema_version") != 1 or payload.get("model_class") != "NeuralTransitionPolicy":
            raise TrainingBindingError("unsupported checkpoint schema or model class")
        if int(payload.get("model_hidden_dim", -1)) != expected_config.hidden_dim:
            raise TrainingBindingError("checkpoint model dimension does not match training config")
        cursor=TrainingCursor(**payload["cursor"])
        if cursor.to_dict()!=checkpoint_record.get("cursor") or meta.get("cursor")!=cursor.to_dict():
            raise TrainingBindingError("checkpoint cursor binding mismatch")
        if cursor.dataset_sha256!=expected_dataset_sha256:
            raise TrainingBindingError("checkpoint dataset hash does not match current training data")
        if cursor.curriculum_manifest_sha256!=expected_binding.manifest_sha256 or cursor.curriculum_splits_sha256!=expected_binding.splits_sha256 or cursor.curriculum_generator_id!=expected_binding.generator_id:
            raise TrainingBindingError("checkpoint curriculum binding does not match current curriculum")
        if cursor.config_hash!=expected_config.config_hash or payload.get("config")!=expected_config.to_dict() or meta.get("config_hash")!=expected_config.config_hash:
            raise TrainingBindingError("checkpoint training config mismatch")
        model=NeuralTransitionPolicy(hidden_dim=int(payload["model_hidden_dim"]))
        model.load_state_dict(payload["model_state"])
        optimizer=torch.optim.AdamW(model.parameters(),lr=expected_config.learning_rate,weight_decay=expected_config.weight_decay)
        optimizer.load_state_dict(payload["optimizer_state"])
        model_hash=hash_torch_state(model.state_dict(),domain="CETA/MODEL_STATE/v1")
        optimizer_hash=hash_torch_state(optimizer.state_dict(),domain="CETA/OPTIMIZER_STATE/v1")
        if model_hash!=payload.get("model_hash") or optimizer_hash!=payload.get("optimizer_hash"):
            raise TrainingBindingError("checkpoint internal state hash mismatch")
        if model_hash!=checkpoint_record.get("model_hash") or optimizer_hash!=checkpoint_record.get("optimizer_hash"):
            raise TrainingBindingError("checkpoint ledger state hash mismatch")
        if meta.get("model_hash")!=model_hash or meta.get("optimizer_hash")!=optimizer_hash:
            raise TrainingBindingError("checkpoint sidecar state hash mismatch")
        resolved_device=_resolve_device(device)
        model.to(resolved_device)
        _move_optimizer_state(optimizer,resolved_device)
        ref=CheckpointRef(str(path),expected_sha,model_hash,optimizer_hash,cursor)
        return model,optimizer,ref

    def activate(self,checkpoint: CheckpointRef) -> None:
        path=Path(checkpoint.path)
        sidecar=path.with_suffix(path.suffix+".json")
        _atomic_json(self.root/"latest.json",{"checkpoint":path.name,"sidecar":sidecar.name,"sha256":checkpoint.sha256})



class GovernedEpochTrainer:
    def __init__(self,*,run_root: str|Path,dataset_path: str|Path,config: TrainingConfig,run_id: str='RUN-0001',resume: bool=False,device: str|torch.device='cpu') -> None:
        self.root=Path(run_root); self.root.mkdir(parents=True,exist_ok=True)
        self.dataset_path=Path(dataset_path)
        if self.dataset_path.name != 'train.jsonl':
            raise TrainingBindingError('governed trainer accepts only the isolated train.jsonl split')
        self.binding=resolve_curriculum_binding(self.dataset_path,split='train')
        self.dataset_sha256=file_sha256(self.dataset_path)
        self.config=config; self.run_id=run_id; self.device=_resolve_device(device)
        self.cases=load_cases(self.dataset_path)
        if not self.cases: raise TrainingBindingError('training dataset is empty')
        self.ledger=TrainingEventLedger(self.root/'training-events.jsonl')
        self.checkpoints=CheckpointStore(self.root/'checkpoints')
        if resume:
            checkpoint_event=self._latest_committed_checkpoint_event()
            self.model,self.optimizer,self.checkpoint=self.checkpoints.load_committed(
                checkpoint_event['payload']['checkpoint'],expected_dataset_sha256=self.dataset_sha256,
                expected_config=config,expected_binding=self.binding,device=self.device,
            )
            self.cursor=self.checkpoint.cursor
            if self.cursor.run_id!=run_id: raise TrainingBindingError('resume run_id mismatch')
            self._reconcile_tail_after_checkpoint(checkpoint_event)
            self.checkpoints.activate(self.checkpoint)
            self.ledger.append('RUN_RESUMED',{'run_id':run_id,'checkpoint_sha256':self.checkpoint.sha256,'cursor':self.cursor.to_dict()})
        else:
            if self.ledger.events: raise TrainingBindingError('new training run cannot reuse a non-empty run ledger')
            torch.manual_seed(config.seed)
            if self.device.type=='cuda': torch.cuda.manual_seed_all(config.seed)
            torch.use_deterministic_algorithms(True)
            self.model=NeuralTransitionPolicy(hidden_dim=config.hidden_dim).to(self.device)
            self.optimizer=torch.optim.AdamW(self.model.parameters(),lr=config.learning_rate,weight_decay=config.weight_decay)
            self.cursor=TrainingCursor(run_id=run_id,epoch_index=0,next_case_offset=0,global_step=0,dataset_sha256=self.dataset_sha256,split='train',config_hash=config.config_hash,curriculum_manifest_sha256=self.binding.manifest_sha256,curriculum_splits_sha256=self.binding.splits_sha256,curriculum_generator_id=self.binding.generator_id)
            self.checkpoint=None
            self.ledger.append('RUN_INITIALIZED',{'run_id':run_id,'dataset_sha256':self.dataset_sha256,'config_hash':config.config_hash,'curriculum_binding':self.binding.to_dict(),'case_count':len(self.cases)})

    def _latest_committed_checkpoint_event(self) -> dict[str,Any]:
        events=[event for event in self.ledger.events if event.get('event_type')=='CHECKPOINT_SAVED']
        if not events:
            raise TrainingBindingError('no committed checkpoint available to resume')
        return events[-1]

    def _reconcile_tail_after_checkpoint(self,checkpoint_event: Mapping[str,Any]) -> None:
        sequence=int(checkpoint_event['sequence'])
        tail=[event for event in self.ledger.events if int(event['sequence'])>sequence]
        advancing=[event for event in tail if event.get('event_type') in {'OPTIMIZER_STEP','EPOCH_COMPLETED'}]
        if not advancing:
            return
        orphaned_sequences=[int(event['sequence']) for event in advancing]
        orphaned_receipts=[event['payload'].get('receipt_hash') for event in advancing if event.get('event_type')=='OPTIMIZER_STEP']
        self.ledger.append('RECOVERY_REWIND',{
            'run_id':self.run_id,'checkpoint_sha256':self.checkpoint.sha256,'cursor':self.cursor.to_dict(),
            'orphaned_event_sequences':orphaned_sequences,'orphaned_optimizer_receipts':[x for x in orphaned_receipts if x],
            'reason_code':'UNCOMMITTED_TRAINING_TAIL',
        })

    def train_cases(self,max_cases: int) -> CheckpointRef:
        if max_cases < 1: raise TrainingBindingError('max_cases must be positive')
        processed=0
        while processed < max_cases:
            order=self._epoch_order(self.cursor.epoch_index)
            if self.cursor.next_case_offset >= len(order):
                self.ledger.append('EPOCH_COMPLETED',{'run_id':self.run_id,'epoch_index':self.cursor.epoch_index,'global_step':self.cursor.global_step,'model_hash':hash_torch_state(self.model.state_dict(),domain='CETA/MODEL_STATE/v1')})
                self.cursor=self._cursor(epoch_index=self.cursor.epoch_index+1,next_case_offset=0,global_step=self.cursor.global_step)
                order=self._epoch_order(self.cursor.epoch_index)
            case=self.cases[order[self.cursor.next_case_offset]]
            self._train_one(case)
            self.cursor=self._cursor(epoch_index=self.cursor.epoch_index,next_case_offset=self.cursor.next_case_offset+1,global_step=self.cursor.global_step+1)
            processed += 1
        # Close an epoch at the exact boundary rather than waiting for a later
        # training call to notice that its final case was already consumed.
        final_order=self._epoch_order(self.cursor.epoch_index)
        if self.cursor.next_case_offset >= len(final_order):
            self.ledger.append('EPOCH_COMPLETED',{'run_id':self.run_id,'epoch_index':self.cursor.epoch_index,'global_step':self.cursor.global_step,'model_hash':hash_torch_state(self.model.state_dict(),domain='CETA/MODEL_STATE/v1')})
            self.cursor=self._cursor(epoch_index=self.cursor.epoch_index+1,next_case_offset=0,global_step=self.cursor.global_step)
        self.checkpoint=self.checkpoints.save(model=self.model,optimizer=self.optimizer,cursor=self.cursor,config=self.config)
        self.ledger.append('CHECKPOINT_SAVED',{'run_id':self.run_id,'checkpoint':self.checkpoint.to_dict()})
        self.checkpoints.activate(self.checkpoint)
        return self.checkpoint

    def _cursor(self,*,epoch_index: int,next_case_offset: int,global_step: int) -> TrainingCursor:
        return TrainingCursor(
            run_id=self.run_id,epoch_index=epoch_index,next_case_offset=next_case_offset,global_step=global_step,
            dataset_sha256=self.dataset_sha256,split='train',config_hash=self.config.config_hash,
            curriculum_manifest_sha256=self.binding.manifest_sha256,curriculum_splits_sha256=self.binding.splits_sha256,
            curriculum_generator_id=self.binding.generator_id,
        )

    def _train_one(self,case: TransitionTrainingCase) -> None:
        self.model.train(); self.optimizer.zero_grad(set_to_none=True)
        before=hash_torch_state(self.model.state_dict(),domain='CETA/MODEL_STATE/v1')
        world=world_from_training_case(case)
        output=self.model.forward_world(world,extra_candidates=candidate_sequence(case))
        losses=compute_ceta_loss(case,output)
        losses.total.backward()
        grad_norm=float(torch.nn.utils.clip_grad_norm_(self.model.parameters(),self.config.gradient_clip_norm).item())
        self.optimizer.step()
        after=hash_torch_state(self.model.state_dict(),domain='CETA/MODEL_STATE/v1')
        optimizer_hash=hash_torch_state(self.optimizer.state_dict(),domain='CETA/OPTIMIZER_STATE/v1')
        receipt={
            'run_id':self.run_id,'epoch_index':self.cursor.epoch_index,'case_offset':self.cursor.next_case_offset,
            'global_step_before':self.cursor.global_step,'case_id':case.case_id,
            'loss':float(losses.total.detach().cpu().item()),'opcode_loss':float(losses.opcode_loss.detach().cpu().item()),
            'transition_rank_loss':float(losses.transition_rank_loss.detach().cpu().item()),
            'failure_surface_loss':float(losses.failure_surface_loss.detach().cpu().item()),
            'gradient_norm':grad_norm,'model_hash_before':before,'model_hash_after':after,'optimizer_hash_after':optimizer_hash,
        }
        receipt['receipt_hash']=domain_hash(receipt,domain='CETA/OPTIMIZER_RECEIPT/v1')
        self.ledger.append('OPTIMIZER_STEP',receipt)

    def _epoch_order(self,epoch_index: int) -> tuple[str,...]:
        seed=self.config.seed
        return tuple(sorted(self.cases,key=lambda cid:hashlib.sha256(f'CETA/EPOCH_ORDER/v1\n{seed}\n{epoch_index}\n{cid}'.encode()).digest()))


class IndependentCheckpointEvaluator:
    """Loads checkpoint into a fresh model and evaluates transition behavior."""
    def __init__(self,*,config: TrainingConfig,device: str|torch.device='cpu') -> None:
        self.config=config; self.device=_resolve_device(device); self.vm=ConstitutionalVM()

    def evaluate(self,checkpoint_path: str|Path,dataset_path: str|Path,*,split: str) -> EvaluationMetrics:
        checkpoint_path=Path(checkpoint_path); dataset_path=Path(dataset_path)
        if split not in {'validation','heldout'} or dataset_path.name != f'{split}.jsonl':
            raise TrainingBindingError('independent evaluator accepts only matching validation.jsonl or heldout.jsonl')
        binding=resolve_curriculum_binding(dataset_path,split=split)
        checkpoint_sha=file_sha256(checkpoint_path)
        sidecar=checkpoint_path.with_suffix(checkpoint_path.suffix+'.json')
        if not sidecar.is_file(): raise TrainingBindingError('checkpoint sidecar missing for evaluation')
        meta=json.loads(sidecar.read_text(encoding='utf-8'))
        if meta.get('sha256')!=checkpoint_sha or meta.get('checkpoint')!=checkpoint_path.name:
            raise TrainingBindingError('checkpoint sidecar does not bind evaluation checkpoint')
        payload=torch.load(checkpoint_path,map_location='cpu',weights_only=True)
        if payload.get('schema_version') != 1 or payload.get('model_class') != 'NeuralTransitionPolicy':
            raise TrainingBindingError('unsupported evaluation checkpoint schema or model class')
        if int(payload.get('model_hidden_dim', -1)) != self.config.hidden_dim:
            raise TrainingBindingError('evaluation checkpoint model dimension mismatch')
        cursor=TrainingCursor(**payload['cursor'])
        if payload.get('config')!=self.config.to_dict() or cursor.config_hash!=self.config.config_hash:
            raise TrainingBindingError('evaluation checkpoint training config mismatch')
        if cursor.curriculum_manifest_sha256!=binding.manifest_sha256 or cursor.curriculum_splits_sha256!=binding.splits_sha256 or cursor.curriculum_generator_id!=binding.generator_id:
            raise TrainingBindingError('evaluation dataset is not bound to the checkpoint curriculum')
        model=NeuralTransitionPolicy(hidden_dim=int(payload['model_hidden_dim']))
        model.load_state_dict(payload['model_state'])
        if hash_torch_state(model.state_dict(),domain='CETA/MODEL_STATE/v1')!=payload.get('model_hash'):
            raise TrainingBindingError('evaluation checkpoint model hash mismatch')
        model.to(self.device); model.eval()
        cases=load_cases(dataset_path)
        target_correct=0; opcode_correct=0; legal=0; loss_total=0.0; rejected=0
        with torch.no_grad():
            for case in cases.values():
                world=world_from_training_case(case)
                output=model.forward_world(world)
                rejected += output.rejected_candidate_count
                chosen_index=int(torch.argmax(output.candidate_scores).item())
                chosen=output.candidate_proposals[chosen_index]
                if _proposal_key(chosen)==_proposal_key(case.target_proposal): target_correct += 1
                if int(torch.argmax(output.opcode_logits).item()) == _operation_index(case.target_proposal.operation): opcode_correct += 1
                decision=self.vm.evaluate(chosen,projected_snapshot=world.snapshot,admitted_evidence_view=world.evidence_view,identity_view=world.identity_view,authority_snapshot=world.authority_view,now_epoch_ms=world.now_epoch_ms,constitutional_epoch='evaluation')
                if decision.disposition is VmDisposition.LEGAL: legal += 1
                loss_total += float(compute_ceta_loss(case,output).total.item())
        n=len(cases)
        body={
            'split':split,'case_count':n,'target_accuracy':target_correct/n,'opcode_accuracy':opcode_correct/n,
            'legal_selection_rate':legal/n,'mean_transition_loss':loss_total/n,'rejected_candidate_count':rejected,
            'checkpoint_sha256':checkpoint_sha,'dataset_sha256':file_sha256(dataset_path),
            'curriculum_manifest_sha256':binding.manifest_sha256,'curriculum_splits_sha256':binding.splits_sha256,
        }
        return EvaluationMetrics(**body,evaluation_hash=domain_hash(body,domain='CETA/INDEPENDENT_EVALUATION/v1'))


class CheckpointPromotionRegistry:
    """Candidate/trusted-head registry. Promotion never mutates checkpoint bytes."""
    def __init__(self,root: str|Path,ledger: TrainingEventLedger) -> None:
        self.root=Path(root); self.root.mkdir(parents=True,exist_ok=True); self.ledger=ledger

    def decide(self,checkpoint: CheckpointRef,metrics: EvaluationMetrics,policy: PromotionPolicy) -> str:
        if metrics.split != 'validation':
            raise TrainingBindingError('checkpoint promotion may use validation evidence only; heldout is reserved for final readiness')
        if metrics.checkpoint_sha256 != checkpoint.sha256:
            raise TrainingBindingError('evaluation is not bound to the checkpoint being promoted')
        if metrics.curriculum_manifest_sha256!=checkpoint.cursor.curriculum_manifest_sha256 or metrics.curriculum_splits_sha256!=checkpoint.cursor.curriculum_splits_sha256:
            raise TrainingBindingError('evaluation curriculum is not bound to the checkpoint curriculum')
        passed,failures=policy.evaluate(metrics)
        status='PROMOTED' if passed else 'QUARANTINED'
        record={'status':status,'checkpoint_sha256':checkpoint.sha256,'checkpoint_path':Path(checkpoint.path).name,'evaluation_hash':metrics.evaluation_hash,'failures':list(failures)}
        _atomic_json(self.root/f'{checkpoint.sha256}.json',record)
        self.ledger.append('CHECKPOINT_'+status,record)
        if passed:
            head={'checkpoint_sha256':checkpoint.sha256,'checkpoint_path':Path(checkpoint.path).name,'evaluation_hash':metrics.evaluation_hash}
            _atomic_json(self.root/'trusted-head.json',head)
        return status

    def rollback(self,checkpoint: CheckpointRef,*,reason_code: str) -> None:
        record_path=self.root/f'{checkpoint.sha256}.json'
        if not record_path.is_file(): raise TrainingBindingError('rollback target checkpoint has no registry record')
        record=json.loads(record_path.read_text(encoding='utf-8'))
        if record.get('status')!='PROMOTED': raise TrainingBindingError('rollback target must have been promoted')
        head={'checkpoint_sha256':checkpoint.sha256,'checkpoint_path':Path(checkpoint.path).name,'evaluation_hash':record['evaluation_hash'],'rollback_reason_code':reason_code}
        _atomic_json(self.root/'trusted-head.json',head)
        self.ledger.append('TRUSTED_HEAD_ROLLBACK',head)


def effective_optimizer_events(events: Sequence[Mapping[str,Any]]) -> tuple[Mapping[str,Any],...]:
    orphaned=set()
    for event in events:
        if event.get('event_type')=='RECOVERY_REWIND':
            orphaned.update(int(x) for x in event.get('payload',{}).get('orphaned_event_sequences',()))
    return tuple(event for event in events if event.get('event_type')=='OPTIMIZER_STEP' and int(event.get('sequence',-1)) not in orphaned)


def resolve_curriculum_binding(path: str|Path,*,split: str) -> CurriculumBinding:
    dataset_path=Path(path)
    if split not in {"train","validation","heldout"}:
        raise TrainingBindingError("unknown curriculum split")
    base=dataset_path.parent
    manifest_path=base/"manifest.json"
    splits_path=base/"splits.json"
    if not manifest_path.is_file() or not splits_path.is_file():
        raise TrainingBindingError("curriculum manifest/splits binding is required")
    try:
        manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
        splits=json.loads(splits_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise TrainingBindingError(f"invalid curriculum binding metadata: {exc}") from exc
    generator_id=str(manifest.get("generator_id",""))
    if not generator_id or splits.get("generator_id")!=generator_id:
        raise TrainingBindingError("curriculum generator binding mismatch")
    splits_sha=file_sha256(splits_path)
    if manifest.get("splits_sha256")!=splits_sha:
        raise TrainingBindingError("curriculum splits hash mismatch")
    files=manifest.get("files")
    if not isinstance(files,dict) or set(files)!={"train","validation","heldout"}:
        raise TrainingBindingError("curriculum manifest must bind train/validation/heldout files")
    for name in ("train","validation","heldout"):
        info=files.get(name)
        if not isinstance(info,dict):
            raise TrainingBindingError(f"curriculum {name} file binding missing")
        filename=str(info.get("path",""))
        if not filename or Path(filename).name!=filename:
            raise TrainingBindingError(f"curriculum {name} path must be a local basename")
        artifact=base/filename
        if not artifact.is_file() or file_sha256(artifact)!=info.get("sha256"):
            raise TrainingBindingError(f"curriculum {name} file hash mismatch")
    info=files[split]
    if dataset_path.name!=info.get("path") or file_sha256(dataset_path)!=info.get("sha256"):
        raise TrainingBindingError(f"{split} dataset is not the manifest-bound split artifact")
    case_splits=splits.get("case_splits",{})
    family_splits=splits.get("family_splits",{})
    if set(case_splits)!={"train","validation","heldout"} or set(family_splits)!={"train","validation","heldout"}:
        raise TrainingBindingError("curriculum split membership map incomplete")
    case_sets={k:set(v) for k,v in case_splits.items()}
    family_sets={k:set(v) for k,v in family_splits.items()}
    if case_sets["train"]&case_sets["validation"] or case_sets["train"]&case_sets["heldout"] or case_sets["validation"]&case_sets["heldout"]:
        raise TrainingBindingError("curriculum case split overlap")
    if family_sets["train"]&family_sets["validation"] or family_sets["train"]&family_sets["heldout"] or family_sets["validation"]&family_sets["heldout"]:
        raise TrainingBindingError("curriculum family split overlap")
    seen_cases=set()
    seen_families=set()
    line_count=0
    for lineno,line in enumerate(dataset_path.read_text(encoding="utf-8").splitlines(),1):
        if not line.strip():
            continue
        line_count+=1
        try:
            raw=json.loads(line)
        except Exception as exc:
            raise TrainingBindingError(f"invalid {split} dataset line {lineno}: {exc}") from exc
        seen_cases.add(str(raw.get("case_id","")))
        seen_families.add(str(raw.get("world_family_id","")))
    if line_count!=int(info.get("count",-1)) or seen_cases!=case_sets[split] or seen_families!=family_sets[split]:
        raise TrainingBindingError(f"{split} dataset membership does not match curriculum split binding")
    return CurriculumBinding(manifest_sha256=file_sha256(manifest_path),splits_sha256=splits_sha,generator_id=generator_id)

def load_cases(path: str|Path) -> dict[str,TransitionTrainingCase]:
    result={}
    for lineno,line in enumerate(Path(path).read_text(encoding='utf-8').splitlines(),1):
        if not line.strip(): continue
        try: case=TransitionTrainingCase.from_record(json.loads(line))
        except Exception as exc: raise TrainingBindingError(f'invalid training dataset line {lineno}: {exc}') from exc
        if case.case_id in result: raise TrainingBindingError(f'duplicate training case ID: {case.case_id}')
        result[case.case_id]=case
    return result


def hash_torch_state(value: Any,*,domain: str) -> str:
    h=hashlib.sha256(); h.update((domain+'\n').encode())
    def visit(x: Any) -> None:
        if torch.is_tensor(x):
            t=x.detach().cpu().contiguous(); h.update(b'T'); h.update(str(t.dtype).encode()); h.update(str(tuple(t.shape)).encode()); h.update(t.numpy().tobytes()); return
        if isinstance(x,Mapping):
            h.update(b'D')
            for k in sorted(x,key=lambda y:str(y)):
                h.update(str(k).encode()); h.update(b'\0'); visit(x[k])
            return
        if isinstance(x,(list,tuple)):
            h.update(b'L'); h.update(str(len(x)).encode())
            for item in x: visit(item)
            return
        if isinstance(x,(str,int,float,bool)) or x is None:
            h.update(b'S'); h.update(repr(x).encode()); return
        raise TrainingBindingError(f'unsupported state type in deterministic hash: {type(x).__name__}')
    visit(value)
    return 'sha256:'+h.hexdigest()


def _resolve_device(device: str|torch.device) -> torch.device:
    try:
        resolved=torch.device(device)
    except (TypeError,RuntimeError) as exc:
        raise TrainingBindingError(f'invalid training device: {device}') from exc
    if resolved.type not in {'cpu','cuda'}:
        raise TrainingBindingError(f'unsupported training device: {resolved.type}')
    if resolved.type=='cuda' and not torch.cuda.is_available():
        raise TrainingBindingError('CUDA training requested but torch.cuda.is_available() is false')
    return resolved


def _move_optimizer_state(optimizer: torch.optim.Optimizer,device: torch.device) -> None:
    for state in optimizer.state.values():
        for key,value in state.items():
            if torch.is_tensor(value): state[key]=value.to(device)


def file_sha256(path: str|Path) -> str:
    h=hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda:handle.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()


def _atomic_json(path: Path,payload: Mapping[str,Any]) -> None:
    path.parent.mkdir(parents=True,exist_ok=True); temp=path.with_suffix(path.suffix+'.tmp')
    raw=(json.dumps(dict(payload),sort_keys=True,separators=(',',':'),ensure_ascii=True)+'\n').encode()
    with temp.open('wb') as handle: handle.write(raw); handle.flush(); os.fsync(handle.fileno())
    os.replace(temp,path); _fsync_dir(path.parent)


def _fsync_dir(path: Path) -> None:
    try:
        fd=os.open(path,os.O_RDONLY)
        try: os.fsync(fd)
        finally: os.close(fd)
    except OSError:
        pass


def _proposal_key(proposal) -> str:
    return canonical_json({'input_state_ref':proposal.input_state_ref,'operation':proposal.operation,'operands':dict(proposal.operands)})


def _operation_index(operation: str) -> int:
    from transition_policy import OPERATION_TO_INDEX
    return OPERATION_TO_INDEX[operation]
