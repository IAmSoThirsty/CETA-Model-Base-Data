"""Project-scoped context/evidence facade; CETA verifies authority and effects."""
from dataclasses import asdict
import hashlib
from datetime import datetime, timezone
from uuid import uuid4

from .decision import (Alternative, AuthorityRef, ChosenAction, DecisionEngine,
                       DecisionRecord, KnownFact, Uncertainty)
from .forge.context import ContextCompiler, context_record, policy_from_dict, state_fingerprint
from .forge.harnesses import create_role_harness
from .forge.ledger import OperationalLedger
from .forge.register import ForgeRegister
from .forge.roles import RoleClass
from .forge.types import (ContextReceipt, Evidence, EvidenceLink, EvidenceMethod,
                          EvidenceRelation, PolicyRule, ScopeFit, Verdict)
from .validation import canonical_bytes, digest, object_hash, strict_loads, text, timestamp, unique_strings


def _json(value):
    return strict_loads(canonical_bytes(value).decode("utf-8"))


class GovernanceContext:
    def __init__(self, journal, project_id):
        self.journal = journal
        self.project_id = text(project_id, "project_id")

    def _ledger(self, task_id=None):
        return OperationalLedger(self.journal, self.project_id, task_id)

    def claims(self):
        return {key: value.as_dict() for key, value in ForgeRegister(self._ledger()).states.items()}

    def role(self, participant_id, role_class, *, task_id):
        return create_role_harness(RoleClass(role_class), participant_id, ForgeRegister(self._ledger(task_id)))

    def compile(self, *, actor_id, task_id, objective, project_context):
        text(actor_id, "actor_id"); text(task_id, "task_id"); text(objective, "objective")
        captured = _json(project_context)
        if not isinstance(captured, dict) or captured.get("project_id") != self.project_id:
            raise ValueError("Project context identity mismatch")
        if captured.get("root") is None and self.project_id != "application":
            raise ValueError("A project context requires its authorized workspace root")
        if captured.get("root") is not None:
            text(captured["root"], "root")
        for field in ("files", "instructions"):
            values = captured.get(field, [])
            if not isinstance(values, list):
                raise ValueError(f"{field} must be a list")
            for entry in values:
                if not isinstance(entry, dict):
                    raise ValueError(f"Invalid {field} entry")
                text(entry.get("path"), "path")
                digest(entry.get("sha256"), "sha256")
                if entry.get("encoding") == "utf-8" and "text" in entry:
                    if not isinstance(entry["text"], str) or type(entry.get("bom", False)) is not bool:
                        raise ValueError("Invalid captured UTF-8 content")
                    raw = entry["text"].encode("utf-8")
                    if entry.get("bom", False):
                        raw = b"\xef\xbb\xbf" + raw
                    if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
                        raise ValueError("Captured file text does not match its raw-byte hash")
        registered_root = self.journal.project(self.project_id)["root"]
        if captured.get("root") != registered_root:
            raise ValueError("Context root differs from registered project")
        snapshot_hash = object_hash(captured)
        ledger = self._ledger(task_id)
        with ledger.transaction():
            register = ForgeRegister(ledger)
            proposal = register.submit_proposal(actor_id=actor_id,
                role_class=RoleClass.ANALYST_SYNTHESIZER.value, text=objective)
            claim = register.open_claim(actor_id=actor_id,
                proposition=f"CETA recorded context object {snapshot_hash} for task {task_id}.")
            evidence = register.ingest_evidence(actor_id=actor_id, evidence=Evidence(
                source="CETA context capture", method=EvidenceMethod.DIRECT_OBSERVATION,
                artifact=f"journal://{self.project_id}/context/{snapshot_hash}", artifact_hash=snapshot_hash,
                limitations="Confirms captured context bytes only. The authorized CETA project adapter captures and revalidates files; this facade does not inspect their contents independently."))
            register.link_evidence(link=EvidenceLink(claim_id=claim.claim_id,
                evidence_id=evidence.evidence_id, relation=EvidenceRelation.SUPPORTS,
                scope_fit=ScopeFit.FULL, submitted_by=actor_id))
            state = register.adjudicate(claim_id=claim.claim_id)
            policy = PolicyRule("ceta-context-capture", "1", (Verdict.SUPPORTED,), require_decision_record=True)
            receipt = ContextCompiler(ledger).compile(actor_id=actor_id, task_id=task_id,
                claim_states=register.states, required_claim_ids=(state.claim_id,), policy=policy)
            unresolved = [s.as_dict() for s in register.states.values()
                          if s.verdict in {Verdict.UNKNOWN, Verdict.UNVERIFIED, Verdict.UNRESOLVED, Verdict.DISPUTED}]
            result = {"project_id": self.project_id, "task_id": task_id,
                "objective": objective, "project_context": captured,
                "receipt": asdict(receipt), "proposal_id": proposal.proposal_id,
                "capture_claim_id": state.claim_id, "capture_evidence_id": evidence.evidence_id,
                "snapshot_hash": snapshot_hash, "unresolved_claims": unresolved}
            result["context_hash"] = object_hash(result)
            self.journal.append(self.project_id, "MODEL001_CONTEXT", result,
                task_id=task_id, actor_id=actor_id)
            return _json(result)

    def validate_context(self, context, *, task_id=None, actor_id=None):
        value = _json(context)
        if value.get("project_id") != self.project_id:
            raise ValueError("Context belongs to another project")
        if task_id is not None and value.get("task_id") != task_id:
            raise ValueError("Context belongs to another task")
        claimed = value.pop("context_hash", None)
        if object_hash(value) != claimed:
            raise ValueError("Context content was altered")
        value["context_hash"] = claimed
        receipt = ContextReceipt(**value["receipt"])
        if actor_id is not None and receipt.actor_id != actor_id:
            raise ValueError("Context actor mismatch")
        ledger = self._ledger()
        compiled = context_record(ledger, receipt)
        register = ForgeRegister(ledger)
        selected = register.selected_current(register.states, compiled["required_claim_ids"])
        if state_fingerprint(selected, policy_from_dict(compiled["policy"])) != receipt.state_fingerprint:
            raise ValueError("Context claim state changed")
        matches = [e for e in self.journal.events(self.project_id, kind="MODEL001_CONTEXT", task_id=value["task_id"])
                   if e["payload"].get("context_hash") == claimed]
        if len(matches) != 1 or matches[0]["payload"] != value:
            raise ValueError("Context was not captured in this project journal")
        return value

    def record_decision(self, *, task_id, actor_id, context, action, authority_ref, rationale):
        text(task_id, "task_id"); text(actor_id, "actor_id"); text(rationale, "rationale")
        action = _json(action)
        if not isinstance(action, dict):
            raise ValueError("Action must be a typed tool proposal")
        text(action.get("tool"), "action.tool")
        if not isinstance(action.get("arguments"), dict):
            raise ValueError("Action arguments must be an object")
        if action.get("consequence_hash") is not None:
            digest(action["consequence_hash"], "consequence_hash")
        authority = _json(authority_ref)
        text(authority.get("authority_id"), "authority_id")
        text(authority.get("capability"), "capability")
        unique_strings(authority.get("scope"), "authority.scope")
        digest(authority.get("authority_hash"), "authority_hash")
        if authority.get("expires_at") is not None:
            timestamp(authority["expires_at"], "authority.expires_at")
        reference = AuthorityRef(authority_id=authority["authority_id"], capability=authority["capability"],
            scope=tuple(authority["scope"]), authority_hash=authority["authority_hash"],
            expires_at=authority.get("expires_at"))
        ledger = self._ledger(task_id)
        with ledger.transaction():
            captured = self.validate_context(context, task_id=task_id, actor_id=actor_id)
            action_id = "action_" + object_hash(action)
            record = DecisionRecord(decision_id="decision_" + uuid4().hex,
                task_id=task_id, actor_id=actor_id, proposal_refs=(captured["proposal_id"],),
                state_fingerprint=captured["receipt"]["state_fingerprint"],
                context_receipt_id=captured["receipt"]["receipt_id"],
                known_facts=(KnownFact(captured["capture_claim_id"], captured["receipt"]["claim_versions"][captured["capture_claim_id"]]),),
                claims_relied_upon=(),
                uncertainties=tuple(Uncertainty(s["proposition"], True, s["claim_id"])
                                    for s in captured["unresolved_claims"]),
                alternatives_considered=(Alternative(action_id, action["tool"], "SELECTED", "AUTHORIZED_REQUEST"),),
                chosen_action=ChosenAction(action_id, action["tool"], "CETA_REGISTERED_TOOL"),
                reason_code="AUTHORIZED_REQUEST", authority=reference,
                evidence_refs=(captured["capture_evidence_id"],),
                recorded_at=datetime.now(timezone.utc).isoformat(), public_rationale=rationale)
            DecisionEngine(ledger).record_decision(record)
            result = {**record.as_dict(), "project_id": self.project_id,
                      "context_hash": captured["context_hash"], "action": action}
            self.journal.append(self.project_id, "MODEL001_DECISION_BINDING", result,
                task_id=task_id, actor_id=actor_id)
            return _json(result)

    def record_evidence(self, *, task_id, actor_id, observation):
        text(task_id, "task_id"); text(actor_id, "actor_id")
        observed = _json(observation)
        if not isinstance(observed, dict):
            raise ValueError("Observation must be an object")
        artifact_hash = object_hash(observed)
        ledger = self._ledger(task_id)
        with ledger.transaction():
            stored = self.journal.append(self.project_id, "MODEL001_OBSERVATION", observed,
                task_id=task_id, actor_id=actor_id)
            evidence = ForgeRegister(ledger).ingest_evidence(actor_id=actor_id, evidence=Evidence(
                source="CETA runtime observation", method=EvidenceMethod.DOCUMENT,
                artifact=f"journal://{self.project_id}/{stored['id']}", artifact_hash=artifact_hash,
                limitations="Recorded adapter observation; its presence alone does not prove success or establish an arbitrary claim."))
            return {"evidence_id": evidence.evidence_id, "artifact_hash": artifact_hash,
                    "observation_id": stored["id"], "project_id": self.project_id, "task_id": task_id}
