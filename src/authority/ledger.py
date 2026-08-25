from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from .model import Permit, PermitStatus, RECONCILABLE, TERMINAL_AFTER_EFFECT


class AuthorityError(RuntimeError): pass
class AuthorityBindingError(AuthorityError): pass
class PermitReuseError(AuthorityError): pass
class PermitExpiredError(AuthorityError): pass


GENESIS_AUTHORITY_HASH = "0" * 64


def canonical_hash(value: Mapping[str, Any]) -> str:
    data=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
    return hashlib.sha256(data).hexdigest()


def _event_hash(body: Mapping[str, Any]) -> str:
    return canonical_hash({"domain":"CETA/AUTHORITY_EVENT/v1",**dict(body)})


@dataclass
class _PermitState:
    permit: Permit
    status: PermitStatus=PermitStatus.ISSUED
    intent_hash: str|None=None
    terminal_hash: str|None=None


@dataclass(frozen=True)
class AuthorityEvent:
    sequence: int
    event_type: str
    permit_id: str
    payload: Mapping[str, Any]
    previous_hash: str
    event_hash: str

    def body(self) -> dict[str, Any]:
        return {
            "sequence":self.sequence,
            "event_type":self.event_type,
            "permit_id":self.permit_id,
            "payload":dict(self.payload),
            "previous_hash":self.previous_hash,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.body(),"event_hash":self.event_hash}


class AuthorityLedger:
    """Single-use authority state machine with optional durable replay.

    The ledger never executes effects. With ``path`` set, every state change is
    appended and fsynced before the in-memory projection advances. Restart
    reconstructs consumed-nonce tombstones from the event chain, preventing
    permit resurrection after process loss.
    """

    def __init__(self, path: str|Path|None=None) -> None:
        self.path=Path(path) if path is not None else None
        self._permits: dict[str,_PermitState]={}
        self._consumed_nonces: set[str]=set()
        self._events: list[AuthorityEvent]=[]
        if self.path is not None and self.path.exists():
            self._load()

    @property
    def events(self) -> tuple[AuthorityEvent,...]:
        return tuple(self._events)

    @property
    def current_root(self) -> str:
        return self._events[-1].event_hash if self._events else GENESIS_AUTHORITY_HASH

    def issue(self, permit: Permit, *, consequence: Mapping[str,Any], now_ms: int) -> None:
        self._validate_issue(permit,consequence=consequence,now_ms=now_ms)
        self._commit_event("ISSUE",permit.permit_id,{"permit":_permit_dict(permit),"consequence":dict(consequence)})

    def prepare(self, permit_id: str, *, consumer_id: str, consumer_key_id: str, consequence: Mapping[str,Any], now_ms: int) -> str:
        s=self._state(permit_id)
        if s.status != PermitStatus.ISSUED:
            raise PermitReuseError(f'cannot prepare from {s.status}')
        self._check_consumer(s,consumer_id,consumer_key_id)
        if now_ms >= s.permit.expires_at_epoch_ms:
            self._commit_event("REVOKE",permit_id,{"reason":"EXPIRED_BEFORE_PREPARE"})
            raise PermitExpiredError('permit expired before preparation')
        ch=canonical_hash(consequence)
        if ch != s.permit.consequence_hash:
            raise AuthorityBindingError('prepared consequence differs from permit')
        material={'permit_id':permit_id,'consumer_id':consumer_id,'consumer_key_id':consumer_key_id,'consequence_hash':ch}
        intent_hash=canonical_hash(material)
        self._commit_event("PREPARE",permit_id,{"intent_hash":intent_hash,"consumer_id":consumer_id,"consumer_key_id":consumer_key_id,"consequence_hash":ch})
        return intent_hash

    def resume_prepared(
        self,
        permit_id: str,
        *,
        consumer_id: str,
        consumer_key_id: str,
        consequence: Mapping[str, Any],
        now_ms: int,
    ) -> str:
        """Return the exact already-persisted intent for crash-safe resume.

        No new authority is created. The prepared consequence and consumer must
        still exactly match the permit, and expiry still fails closed.
        """
        s = self._state(permit_id)
        if s.status != PermitStatus.PREPARED or not s.intent_hash:
            raise AuthorityBindingError("permit is not in a resumable PREPARED state")
        self._check_consumer(s, consumer_id, consumer_key_id)
        if now_ms >= s.permit.expires_at_epoch_ms:
            self._commit_event("REVOKE", permit_id, {"reason": "EXPIRED_BEFORE_RESUME"})
            raise PermitExpiredError("permit expired before prepared-intent resume")
        ch = canonical_hash(consequence)
        if ch != s.permit.consequence_hash:
            raise AuthorityBindingError("resumed consequence differs from permit")
        expected = canonical_hash({
            "permit_id": permit_id,
            "consumer_id": consumer_id,
            "consumer_key_id": consumer_key_id,
            "consequence_hash": ch,
        })
        if expected != s.intent_hash:
            raise AuthorityBindingError("persisted prepared intent does not reconstruct")
        return s.intent_hash

    def consume(self, permit_id: str, *, consumer_id: str, consumer_key_id: str, intent_hash: str, now_ms: int) -> None:
        s=self._state(permit_id)
        if s.status != PermitStatus.PREPARED:
            raise PermitReuseError(f'cannot consume from {s.status}')
        self._check_consumer(s,consumer_id,consumer_key_id)
        if now_ms >= s.permit.expires_at_epoch_ms:
            self._commit_event("REVOKE",permit_id,{"reason":"EXPIRED_BEFORE_CONSUME"})
            raise PermitExpiredError('permit expired before consumption')
        if intent_hash != s.intent_hash:
            raise AuthorityBindingError('consumption intent hash mismatch')
        if s.permit.nonce in self._consumed_nonces:
            raise PermitReuseError('permit nonce already consumed')
        self._commit_event("CONSUME",permit_id,{"intent_hash":intent_hash,"nonce":s.permit.nonce})

    def finish(self, permit_id: str, *, status: PermitStatus, expected_consequence_hash: str, actual_consequence_hash: str|None) -> None:
        s=self._state(permit_id)
        if s.status != PermitStatus.CONSUMED:
            raise PermitReuseError(f'cannot finish from {s.status}')
        if status not in TERMINAL_AFTER_EFFECT:
            raise AuthorityBindingError('invalid terminal effect status')
        if expected_consequence_hash != s.permit.consequence_hash:
            raise AuthorityBindingError('receipt expectation differs from permit')
        if status == PermitStatus.COMPLETED and actual_consequence_hash != s.permit.consequence_hash:
            raise AuthorityBindingError('completed effect differs from permitted consequence')
        self._commit_event("FINISH",permit_id,{"status":status.value,"expected_consequence_hash":expected_consequence_hash,"actual_consequence_hash":actual_consequence_hash})

    def reconcile(self, permit_id: str, *, resolved_status: PermitStatus) -> None:
        s=self._state(permit_id)
        if s.status != PermitStatus.INDETERMINATE:
            raise AuthorityBindingError('only indeterminate effects may be reconciled')
        if resolved_status not in RECONCILABLE:
            raise AuthorityBindingError('invalid reconciliation status')
        self._commit_event("RECONCILE",permit_id,{"resolved_status":resolved_status.value})

    def revoke(self, permit_id: str) -> None:
        s=self._state(permit_id)
        if s.status not in {PermitStatus.ISSUED,PermitStatus.PREPARED}:
            raise AuthorityBindingError('only unconsumed authority may be revoked')
        self._commit_event("REVOKE",permit_id,{"reason":"EXPLICIT_REVOCATION"})

    def permit(self, permit_id: str) -> Permit:
        return self._state(permit_id).permit

    def status(self, permit_id: str) -> PermitStatus:
        return self._state(permit_id).status

    def consumed(self, nonce: str) -> bool:
        return nonce in self._consumed_nonces

    def snapshot(self) -> dict[str, Any]:
        """Read-only operational authority view for the Constitutional VM.

        This view is produced by the authority owner itself; callers cannot
        supply or widen permit status through the runtime API.
        """
        return {
            "authority_root": self.current_root,
            "permits": {
                pid: {
                    "permit_id": state.permit.permit_id,
                    "nonce": state.permit.nonce,
                    "policy_epoch": state.permit.policy_epoch,
                    "subject_scope": state.permit.subject_scope,
                    "operation": state.permit.operation,
                    "consequence_hash": state.permit.consequence_hash,
                    "consumer_id": state.permit.consumer_id,
                    "consumer_key_id": state.permit.consumer_key_id,
                    "expires_at_epoch_ms": state.permit.expires_at_epoch_ms,
                    "source_refs": list(state.permit.source_refs),
                    "status": state.status.value,
                    "intent_hash": state.intent_hash,
                }
                for pid, state in sorted(self._permits.items())
            },
        }

    def verify(self) -> bool:
        replay=AuthorityLedger()
        previous=GENESIS_AUTHORITY_HASH
        expected_sequence=1
        for event in self._events:
            if event.sequence != expected_sequence:
                raise AuthorityBindingError('authority event sequence mismatch')
            if event.previous_hash != previous:
                raise AuthorityBindingError('authority event previous hash mismatch')
            if _event_hash(event.body()) != event.event_hash:
                raise AuthorityBindingError('authority event hash mismatch')
            replay._apply_event(event,validate_replay=True)
            previous=event.event_hash
            expected_sequence += 1
        if _state_fingerprint(replay) != _state_fingerprint(self):
            raise AuthorityBindingError('authority replay state mismatch')
        return True

    def _validate_issue(self, permit: Permit, *, consequence: Mapping[str,Any], now_ms: int) -> None:
        if permit.use_limit != 1:
            raise AuthorityBindingError('permit use_limit must equal 1')
        if not permit.subject_scope.strip():
            raise AuthorityBindingError('permit subject_scope must be explicit and non-empty')
        if not permit.operation.strip() or not permit.consumer_id.strip() or not permit.consumer_key_id.strip():
            raise AuthorityBindingError('operation and consumer bindings must be explicit')
        if permit.expires_at_epoch_ms <= now_ms:
            raise PermitExpiredError('permit expiry must be in the future at issue time')
        if canonical_hash(consequence) != permit.consequence_hash:
            raise AuthorityBindingError('permit consequence hash does not match exact consequence')
        if permit.permit_id in self._permits or permit.nonce in self._consumed_nonces or any(s.permit.nonce==permit.nonce for s in self._permits.values()):
            raise PermitReuseError('permit id or nonce already exists')

    def _commit_event(self,event_type: str,permit_id: str,payload: Mapping[str,Any]) -> AuthorityEvent:
        body={
            "sequence":len(self._events)+1,
            "event_type":event_type,
            "permit_id":permit_id,
            "payload":dict(payload),
            "previous_hash":self.current_root,
        }
        event=AuthorityEvent(**body,event_hash=_event_hash(body))
        # Validate against a clone first so an illegal event can never reach disk.
        clone=self._clone_state_only()
        clone._apply_event(event,validate_replay=True)
        if self.path is not None:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            with self.path.open('a',encoding='utf-8',newline='\n') as handle:
                handle.write(json.dumps(event.to_dict(),sort_keys=True,separators=(',',':'),ensure_ascii=True)+'\n')
                handle.flush(); os.fsync(handle.fileno())
        self._apply_event(event,validate_replay=True)
        self._events.append(event)
        return event

    def _apply_event(self,event: AuthorityEvent,*,validate_replay: bool) -> None:
        et=event.event_type; pid=event.permit_id; p=event.payload
        if et=="ISSUE":
            permit=_permit_from_dict(p['permit']); consequence=p['consequence']
            self._validate_issue(permit,consequence=consequence,now_ms=-1)
            self._permits[pid]=_PermitState(permit=permit)
            return
        s=self._state(pid)
        if et=="PREPARE":
            if s.status != PermitStatus.ISSUED: raise AuthorityBindingError('replay PREPARE from invalid state')
            self._check_consumer(s,str(p['consumer_id']),str(p['consumer_key_id']))
            if p['consequence_hash'] != s.permit.consequence_hash: raise AuthorityBindingError('replay PREPARE consequence mismatch')
            s.intent_hash=str(p['intent_hash']); s.status=PermitStatus.PREPARED; return
        if et=="CONSUME":
            if s.status != PermitStatus.PREPARED: raise AuthorityBindingError('replay CONSUME from invalid state')
            if p['intent_hash'] != s.intent_hash or p['nonce'] != s.permit.nonce: raise AuthorityBindingError('replay CONSUME binding mismatch')
            if s.permit.nonce in self._consumed_nonces: raise AuthorityBindingError('replay nonce double consumption')
            self._consumed_nonces.add(s.permit.nonce); s.status=PermitStatus.CONSUMED; return
        if et=="FINISH":
            if s.status != PermitStatus.CONSUMED: raise AuthorityBindingError('replay FINISH from invalid state')
            status=PermitStatus(p['status'])
            if status not in TERMINAL_AFTER_EFFECT: raise AuthorityBindingError('replay invalid terminal status')
            if p['expected_consequence_hash'] != s.permit.consequence_hash: raise AuthorityBindingError('replay expectation mismatch')
            if status==PermitStatus.COMPLETED and p['actual_consequence_hash'] != s.permit.consequence_hash: raise AuthorityBindingError('replay completed consequence mismatch')
            s.status=status; s.terminal_hash=p['actual_consequence_hash']; return
        if et=="RECONCILE":
            if s.status != PermitStatus.INDETERMINATE: raise AuthorityBindingError('replay RECONCILE from invalid state')
            status=PermitStatus(p['resolved_status'])
            if status not in RECONCILABLE: raise AuthorityBindingError('replay invalid reconciliation status')
            s.status=status; return
        if et=="REVOKE":
            if s.status not in {PermitStatus.ISSUED,PermitStatus.PREPARED}: raise AuthorityBindingError('replay REVOKE after effect boundary')
            s.status=PermitStatus.REVOKED; return
        raise AuthorityBindingError(f'unknown authority event type: {et}')

    def _clone_state_only(self) -> 'AuthorityLedger':
        clone=AuthorityLedger()
        clone._permits={pid:_PermitState(state.permit,state.status,state.intent_hash,state.terminal_hash) for pid,state in self._permits.items()}
        clone._consumed_nonces=set(self._consumed_nonces)
        return clone

    def _load(self) -> None:
        events=[]; previous=GENESIS_AUTHORITY_HASH; expected=1
        with self.path.open(encoding='utf-8') as handle:
            for lineno,line in enumerate(handle,1):
                if not line.strip(): continue
                try:
                    raw=json.loads(line)
                    required={'sequence','event_type','permit_id','payload','previous_hash','event_hash'}
                    if set(raw)!=required: raise AuthorityBindingError('authority event field set mismatch')
                    event=AuthorityEvent(int(raw['sequence']),str(raw['event_type']),str(raw['permit_id']),dict(raw['payload']),str(raw['previous_hash']),str(raw['event_hash']))
                    if event.sequence != expected: raise AuthorityBindingError('authority event sequence mismatch')
                    if event.previous_hash != previous: raise AuthorityBindingError('authority previous hash mismatch')
                    if _event_hash(event.body()) != event.event_hash: raise AuthorityBindingError('authority event hash mismatch')
                    self._apply_event(event,validate_replay=True)
                    events.append(event); previous=event.event_hash; expected += 1
                except Exception as exc:
                    raise AuthorityBindingError(f'invalid authority ledger line {lineno}: {exc}') from exc
        self._events=events

    def _state(self, permit_id: str) -> _PermitState:
        try: return self._permits[permit_id]
        except KeyError as e: raise AuthorityBindingError('unknown permit') from e

    @staticmethod
    def _check_consumer(s: _PermitState, consumer_id: str, consumer_key_id: str) -> None:
        if consumer_id != s.permit.consumer_id or consumer_key_id != s.permit.consumer_key_id:
            raise AuthorityBindingError('consumer identity/key mismatch')


def _permit_dict(p: Permit) -> dict[str,Any]:
    d=asdict(p); d['source_refs']=list(p.source_refs); return d


def _permit_from_dict(d: Mapping[str,Any]) -> Permit:
    return Permit(
        permit_id=str(d['permit_id']),nonce=str(d['nonce']),policy_epoch=str(d['policy_epoch']),subject_scope=str(d['subject_scope']),
        operation=str(d['operation']),consequence_hash=str(d['consequence_hash']),consumer_id=str(d['consumer_id']),consumer_key_id=str(d['consumer_key_id']),
        expires_at_epoch_ms=int(d['expires_at_epoch_ms']),source_refs=tuple(str(x) for x in d['source_refs']),use_limit=int(d.get('use_limit',1)))


def _state_fingerprint(ledger: AuthorityLedger) -> str:
    body={
        'permits':{pid:{'permit':_permit_dict(s.permit),'status':s.status.value,'intent_hash':s.intent_hash,'terminal_hash':s.terminal_hash} for pid,s in sorted(ledger._permits.items())},
        'consumed_nonces':sorted(ledger._consumed_nonces),
    }
    return canonical_hash(body)
