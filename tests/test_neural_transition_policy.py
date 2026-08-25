from __future__ import annotations

import inspect
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))

import torch

from ceta import TransitionProposal
from training import CetaWorldCurriculum
from transition_policy import (
    CETA_OPERATION_VOCAB, CetaActionSpaceGenerator, NeuralTransitionPolicy, OPERATION_TO_INDEX,
    StructuredStateEncoder, candidate_sequence, compute_ceta_loss, world_from_training_case,
)


def proposal_key(p: TransitionProposal) -> tuple[str, str]:
    return p.operation, json.dumps(dict(p.operands), sort_keys=True, separators=(',', ':'))


class NeuralTransitionPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases=CetaWorldCurriculum(families_per_operation=10,variants_per_family=1).build()

    def setUp(self):
        torch.manual_seed(7)
        self.model=NeuralTransitionPolicy(hidden_dim=32)

    def test_decoder_vocabulary_is_exactly_23_ceta_opcodes(self):
        registry=json.loads((ROOT/'registry/ceta_operations.json').read_text())['operations']
        self.assertEqual(set(CETA_OPERATION_VOCAB),set(registry))
        self.assertEqual(len(CETA_OPERATION_VOCAB),23)

    def test_forward_has_opcode_candidate_and_failure_heads(self):
        case=self.cases[0]
        out=self.model.forward_world(
            world_from_training_case(case),
            extra_candidates=candidate_sequence(case),
        )
        self.assertEqual(tuple(out.opcode_logits.shape),(23,))
        self.assertEqual(out.candidate_scores.ndim,1)
        self.assertEqual(out.candidate_failure_logits.shape[0],out.candidate_scores.shape[0])
        self.assertEqual(out.candidate_failure_logits.shape[1],9)
        self.assertGreaterEqual(out.rejected_candidate_count,1)  # unknown-op hostile candidate is structurally impossible

    def test_unknown_opcode_cannot_be_emitted(self):
        case=self.cases[0]
        candidates=(TransitionProposal(case.state_ref,'NOT_CETA',{},'x'),)
        out=self.model.forward_world(world_from_training_case(case),extra_candidates=candidates)
        self.assertGreaterEqual(out.rejected_candidate_count,1)
        self.assertTrue(all(p.operation in OPERATION_TO_INDEX for p in out.candidate_proposals))

    def test_loss_is_transition_structural_and_backpropagates(self):
        case=self.cases[33]
        out=self.model.forward_world(
            world_from_training_case(case),
            extra_candidates=candidate_sequence(case),
        )
        result=compute_ceta_loss(case,out)
        self.assertTrue(torch.isfinite(result.total))
        result.total.backward()
        self.assertTrue(any(p.grad is not None and torch.isfinite(p.grad).all() for p in self.model.parameters()))

    def test_symbol_identity_renaming_does_not_change_numeric_world_shape(self):
        a=CetaWorldCurriculum(families_per_operation=10,variants_per_family=2).build()
        by_family={}
        for case in a:
            by_family.setdefault(case.world_family_id,[]).append(case)
        pair=next(v for v in by_family.values() if len(v)==2)
        enc=StructuredStateEncoder()
        wa=enc.encode_world(world_from_training_case(pair[0])); wb=enc.encode_world(world_from_training_case(pair[1]))
        self.assertTrue(torch.equal(wa.node_type,wb.node_type))
        self.assertTrue(torch.equal(wa.node_status,wb.node_status))
        self.assertTrue(torch.equal(wa.node_numeric,wb.node_numeric))
        self.assertTrue(torch.equal(wa.global_numeric,wb.global_numeric))

    def test_target_is_recoverable_without_target_candidate_injection(self):
        generator=CetaActionSpaceGenerator()
        for case in self.cases:
            target=proposal_key(case.target_proposal)
            adversarial={proposal_key(p) for p in candidate_sequence(case)}
            self.assertNotIn(target,adversarial)
            generated={proposal_key(p) for p in generator.generate(world_from_training_case(case))}
            self.assertIn(target,generated,case.case_id)

    def test_propose_has_no_candidate_parameter_and_selects_generated_action(self):
        params=tuple(inspect.signature(NeuralTransitionPolicy.propose).parameters)
        self.assertEqual(params,('self','world'))
        case=self.cases[5]
        world=world_from_training_case(case)
        generated={proposal_key(p) for p in CetaActionSpaceGenerator().generate(world)}
        chosen=self.model.propose(world)
        self.assertIn(proposal_key(chosen),generated)
        self.assertEqual(chosen.proposer_id,self.model.model_id)

    def test_inference_forward_uses_only_target_blind_action_space(self):
        case=self.cases[77]
        world=world_from_training_case(case)
        out=self.model.forward_world(world)
        generated={proposal_key(p) for p in CetaActionSpaceGenerator().generate(world)}
        emitted={proposal_key(p) for p in out.candidate_proposals}
        self.assertEqual(emitted,generated)


if __name__=='__main__': unittest.main()
