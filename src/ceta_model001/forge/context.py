from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from ..validation import object_hash, text, timestamp
from .register import ForgeRegister
from .types import ClaimState, ContextReceipt, PolicyRule, Verdict


def policy_dict(policy):
    policy.validate()
    value = asdict(policy)
    value['allowed_verdicts'] = [v.value for v in policy.allowed_verdicts]
    return value


def policy_from_dict(value):
    value = dict(value)
    value['allowed_verdicts'] = tuple(Verdict(v) for v in value['allowed_verdicts'])
    policy = PolicyRule(**value); policy.validate()
    return policy


def state_fingerprint(claim_states: dict[str, ClaimState], policy: PolicyRule) -> str:
    for cid, state in claim_states.items():
        if not isinstance(state, ClaimState) or cid != state.claim_id: raise ValueError('Claim key/identity mismatch')
    return object_hash({'claims': {cid: state.as_dict() for cid, state in sorted(claim_states.items())},
                        'policy': policy_dict(policy)})


def context_record(ledger, receipt):
    if not isinstance(receipt, ContextReceipt): raise ValueError('Expected ContextReceipt')
    value = asdict(receipt); claimed_hash = value.pop('receipt_hash')
    if object_hash(value) != claimed_hash: raise ValueError('Context receipt hash mismatch')
    issued, expires = timestamp(receipt.issued_at), timestamp(receipt.expires_at)
    now = datetime.now(timezone.utc)
    if issued > now or expires <= issued or now >= expires: raise ValueError('Context receipt expired or invalid time window')
    matches = [e for e in ledger.records() if e['event_type'] == 'CONTEXT_COMPILED'
        and e['payload'].get('receipt', {}).get('receipt_id') == receipt.receipt_id]
    if len(matches) != 1 or matches[0]['actor_id'] != 'system:context-compiler' or matches[0]['payload'].get('receipt') != asdict(receipt):
        raise ValueError('Context receipt was not issued by this ledger or was altered')
    return matches[0]['payload']


class ContextCompiler:
    def __init__(self, ledger): self.ledger = ledger

    def compile(self, *, actor_id, task_id, claim_states, required_claim_ids, policy, ttl_seconds=300):
        text(actor_id, 'actor_id'); text(task_id, 'task_id')
        if type(ttl_seconds) is not int or ttl_seconds <= 0: raise ValueError('ttl_seconds must be a positive integer')
        body = policy_dict(policy)
        with self.ledger.transaction():
            register = ForgeRegister(self.ledger)
            selected = register.selected_current(claim_states, required_claim_ids)
            for event in self.ledger.records():
                old = event['payload'].get('policy', {}) if event['event_type'] == 'CONTEXT_COMPILED' else {}
                if old.get('policy_id') == policy.policy_id and old.get('version') == policy.version and old != body:
                    raise ValueError('Policy body changed without a version change')
            issued = datetime.now(timezone.utc)
            try: expires = issued + timedelta(seconds=ttl_seconds)
            except OverflowError as exc: raise ValueError('Invalid context lifetime') from exc
            base = {'receipt_id': 'ctx_' + uuid4().hex[:16], 'actor_id': actor_id, 'task_id': task_id,
                'state_fingerprint': state_fingerprint(selected, policy),
                'claim_versions': {cid: st.version for cid, st in sorted(selected.items())},
                'policy_id': policy.policy_id, 'policy_version': policy.version,
                'issued_at': issued.isoformat(), 'expires_at': expires.isoformat()}
            if any(e['payload'].get('receipt', {}).get('receipt_id') == base['receipt_id'] for e in self.ledger.records()):
                raise ValueError('Generated receipt identity collision')
            receipt = ContextReceipt(receipt_hash=object_hash(base), **base)
            self.ledger.append(event_type='CONTEXT_COMPILED', actor_id='system:context-compiler', task_id=task_id,
                payload={'receipt': asdict(receipt), 'policy': body, 'required_claim_ids': list(required_claim_ids)})
            return receipt
