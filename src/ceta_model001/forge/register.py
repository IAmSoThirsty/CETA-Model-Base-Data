from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from types import MappingProxyType
from uuid import uuid4

from ..validation import text, timestamp, unique_strings
from .adjudicator import Adjudicator
from .ledger import OperationalLedger, LedgerIntegrityError
from .roles import RoleClass
from .types import (ClaimRecord, ClaimState, Evidence, EvidenceLink, Proposal,
    QuestionPlane, BasisClass, Verdict, EvidenceMethod, EvidenceRelation, ScopeFit, now_iso)


class IllegalWrite(RuntimeError): pass
class DuplicateIdentity(RuntimeError): pass


def state_from_dict(value):
    value = dict(value)
    value['question_plane'] = QuestionPlane(value['question_plane'])
    value['basis'] = BasisClass(value['basis'])
    value['verdict'] = Verdict(value['verdict'])
    for field in ('evidence_refs', 'counterevidence_refs', 'contextual_evidence_refs', 'dependencies'):
        value[field] = tuple(value.get(field, ()))
    return ClaimState(**value)


class ForgeRegister:
    """A verified projection of history; public views cannot write canonical state."""

    def __init__(self, ledger: OperationalLedger):
        self.ledger = ledger
        self.adjudicator = Adjudicator()
        self._sync()

    def _sync(self):
        claims, states, evidence, proposals = {}, {}, {}, {}
        history, challenges = defaultdict(list), defaultdict(list)
        links, dirty, ids, operations = [], set(), set(), set()
        def identity(value):
            text(value, 'identity')
            if value in ids: raise DuplicateIdentity(f'Duplicate identity: {value}')
            ids.add(value)
        try:
            for event in self.ledger.records():
                kind, p = event['event_type'], event['payload']
                if kind == 'CLAIM_OPENED':
                    identity(p['claim_id'])
                    text(p['proposition'], 'proposition')
                    deps = tuple(p.get('dependencies', ()))
                    unique_strings(deps, 'dependencies')
                    if any(cid not in claims for cid in deps): raise ValueError('Unknown claim dependency')
                    claims[p['claim_id']] = ClaimRecord(p['claim_id'], p['proposition'],
                        QuestionPlane(p['question_plane']), p.get('created_at', event['committed_at']), event['actor_id'], deps)
                    dirty.add(p['claim_id'])
                elif kind == 'EVIDENCE_INGESTED':
                    q = dict(p); q['method'] = EvidenceMethod(q['method'])
                    q['identity_relevance_evidence_refs'] = tuple(q.get('identity_relevance_evidence_refs', ()))
                    ev = Evidence(**q); ev.validate(); identity(ev.evidence_id)
                    if any(ref not in evidence for ref in ev.identity_relevance_evidence_refs):
                        raise ValueError('Missing identity-relevance evidence')
                    evidence[ev.evidence_id] = ev
                elif kind == 'EVIDENCE_LINKED':
                    q = dict(p); q['relation'] = EvidenceRelation(q['relation']); q['scope_fit'] = ScopeFit(q['scope_fit'])
                    link = EvidenceLink(**q); link.validate(); identity(link.operation_id)
                    if link.claim_id not in claims or link.evidence_id not in evidence:
                        raise ValueError('Dangling evidence operation')
                    if link.submitted_by != event['actor_id']: raise ValueError('Evidence actor mismatch')
                    key = (link.claim_id, link.evidence_id, link.relation, link.scope_fit)
                    if key in operations: raise DuplicateIdentity('Duplicate semantic evidence operation')
                    operations.add(key); links.append(link); dirty.add(link.claim_id)
                elif kind == 'PROPOSAL_SUBMITTED':
                    proposal = Proposal(**p); identity(proposal.proposal_id)
                    text(proposal.text, 'proposal text'); RoleClass(proposal.role_class)
                    timestamp(proposal.submitted_at)
                    if proposal.actor_id != event['actor_id']: raise ValueError('Proposal actor mismatch')
                    if proposal.about_claim is not None and proposal.about_claim not in claims:
                        raise ValueError('Unknown proposal claim')
                    proposals[proposal.proposal_id] = proposal
                elif kind == 'CLAIM_CHALLENGED':
                    identity(p['challenge_id']); text(p['reason'], 'challenge reason')
                    if p['claim_id'] not in claims or p['actor_id'] != event['actor_id']:
                        raise ValueError('Invalid challenge binding')
                    challenges[p['claim_id']].append(dict(p)); dirty.add(p['claim_id'])
                elif kind == 'ADJUDICATION_COMMITTED':
                    state = state_from_dict(p['state'])
                    if event['actor_id'] != 'system:forge-adjudicator': raise ValueError('Invalid adjudicator actor')
                    if state.claim_id not in claims: raise ValueError('Adjudication without a claim')
                    if type(state.version) is not int: raise ValueError('Invalid claim version')
                    expected = self.adjudicator.derive(claims[state.claim_id], evidence, links,
                        states.get(state.claim_id), reason=state.supersession_reason, adjudicated_at=state.updated_at)
                    if state.adjudicator_version == 'forge-adjudicator-0.1':
                        expected = replace(expected, adjudicator_version=state.adjudicator_version)
                    if expected != state: raise ValueError('Claim projection does not match deterministic adjudication')
                    states[state.claim_id] = state; history[state.claim_id].append(state); dirty.discard(state.claim_id)
        except (KeyError, TypeError, ValueError, DuplicateIdentity) as exc:
            raise LedgerIntegrityError(f'Invalid operational history: {exc}') from exc
        self._claims, self._states, self._evidence, self._proposals = claims, states, evidence, proposals
        self._history, self._challenges, self._links, self._dirty, self._ids = history, challenges, links, dirty, ids

    @property
    def claims(self):
        self._sync(); return MappingProxyType(dict(self._claims))
    @property
    def states(self):
        self._sync(); return MappingProxyType(dict(self._states))
    @property
    def evidence(self):
        self._sync(); return MappingProxyType(dict(self._evidence))
    @property
    def proposals(self):
        self._sync(); return MappingProxyType(dict(self._proposals))
    @property
    def links(self):
        self._sync(); return tuple(self._links)
    @property
    def history(self):
        self._sync(); return MappingProxyType({k: tuple(v) for k, v in self._history.items()})
    @property
    def challenges(self):
        self._sync(); return {k: [dict(v) for v in values] for k, values in self._challenges.items()}

    def _new_id(self, prefix):
        identity = prefix + uuid4().hex[:16]
        if identity in self._ids: raise DuplicateIdentity('Generated identity collision')
        return identity

    def open_claim(self, *, actor_id, proposition, question_plane=QuestionPlane.HAPPENED, dependencies=()):
        text(actor_id, 'actor_id'); text(proposition, 'proposition')
        if not isinstance(question_plane, QuestionPlane): raise ValueError('Invalid question plane')
        unique_strings(dependencies, 'dependencies')
        with self.ledger.transaction():
            self._sync()
            if any(cid not in self._claims for cid in dependencies): raise IllegalWrite('Unknown claim dependency')
            cid, created = self._new_id('cl_'), now_iso()
            record = ClaimRecord(cid, proposition, question_plane, created, actor_id, tuple(dependencies))
            state = self.adjudicator.derive(record, self._evidence, self._links, None, reason='Claim opened')
            self.ledger.append(event_type='CLAIM_OPENED', actor_id=actor_id, payload={
                'claim_id': cid, 'proposition': proposition, 'question_plane': question_plane.value,
                'dependencies': list(dependencies), 'created_at': created})
            self._commit_state(state, reason='Initial UNKNOWN state')
            return state

    def submit_proposal(self, *, actor_id, role_class, text: str, about_claim=None):
        from ..validation import text as require_text
        require_text(actor_id, 'actor_id'); require_text(text, 'proposal text'); RoleClass(role_class)
        with self.ledger.transaction():
            self._sync()
            if about_claim is not None and about_claim not in self._claims: raise IllegalWrite('Unknown claim')
            proposal = Proposal(actor_id=actor_id, role_class=RoleClass(role_class).value, text=text,
                about_claim=about_claim, proposal_id=self._new_id('pr_'))
            self.ledger.append(event_type='PROPOSAL_SUBMITTED', actor_id=actor_id, payload=proposal.as_dict())
            return proposal

    def ingest_evidence(self, *, actor_id, evidence):
        text(actor_id, 'actor_id')
        if not isinstance(evidence, Evidence): raise ValueError('Expected Evidence')
        evidence.validate()
        with self.ledger.transaction():
            self._sync()
            if evidence.evidence_id in self._ids: raise DuplicateIdentity('Evidence identity already exists')
            if any(ref not in self._evidence for ref in evidence.identity_relevance_evidence_refs):
                raise IllegalWrite('Unknown identity-relevance evidence')
            self.ledger.append(event_type='EVIDENCE_INGESTED', actor_id=actor_id, payload=evidence.as_dict())
            return evidence

    def link_evidence(self, *, link):
        if not isinstance(link, EvidenceLink): raise ValueError('Expected EvidenceLink')
        link.validate()
        with self.ledger.transaction():
            self._sync()
            if link.claim_id not in self._claims or link.evidence_id not in self._evidence:
                raise IllegalWrite('Unknown claim or evidence')
            if link.operation_id in self._ids: raise DuplicateIdentity('Evidence operation identity already exists')
            key = lambda item: (item.claim_id, item.evidence_id, item.relation, item.scope_fit)
            if any(key(item) == key(link) for item in self._links): raise DuplicateIdentity('Duplicate semantic evidence operation')
            self.ledger.append(event_type='EVIDENCE_LINKED', actor_id=link.submitted_by, payload=link.as_dict())
            return link

    def challenge_claim(self, *, actor_id, claim_id, reason):
        text(actor_id, 'actor_id'); text(reason, 'challenge reason')
        with self.ledger.transaction():
            self._sync()
            if claim_id not in self._claims: raise IllegalWrite('Unknown claim')
            self.ledger.append(event_type='CLAIM_CHALLENGED', actor_id=actor_id, payload={
                'claim_id': claim_id, 'challenge_id': self._new_id('ch_'), 'actor_id': actor_id, 'reason': reason, 'at': now_iso()})

    def adjudicate(self, *, claim_id, reason=None):
        if reason is not None: text(reason, 'adjudication reason')
        with self.ledger.transaction():
            self._sync()
            if claim_id not in self._claims: raise IllegalWrite('Unknown claim')
            state = self.adjudicator.derive(self._claims[claim_id], self._evidence, self._links,
                self._states.get(claim_id), reason=reason)
            self._commit_state(state, reason=reason or 'Deterministic adjudication')
            return state

    def current(self, claim_id):
        self._sync()
        if claim_id not in self._states: raise IllegalWrite(f'Unknown claim {claim_id}')
        return self._states[claim_id]

    def selected_current(self, claim_states, required_claim_ids):
        unique_strings(required_claim_ids, 'required_claim_ids')
        if not required_claim_ids: raise ValueError('At least one required claim is necessary')
        self._sync()
        selected = {}
        def select(cid):
            if cid in selected: return
            if cid not in self._states or cid in self._dirty: raise ValueError('Missing or stale claim projection')
            state = self._states[cid]
            if cid not in claim_states or claim_states[cid] != state: raise ValueError('Caller claim projection differs from canonical history')
            selected[cid] = state
            for dep in state.dependencies: select(dep)
        for cid in required_claim_ids: select(cid)
        return selected

    def _commit_state(self, state, *, reason):
        self.ledger.append(event_type='ADJUDICATION_COMMITTED', actor_id='system:forge-adjudicator',
            payload={'state': state.as_dict(), 'reason': reason})
