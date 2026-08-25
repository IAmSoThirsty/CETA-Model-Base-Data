import sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from ceta import ConstitutionalVM, ProposalBindingError, TransitionProposal, VmDisposition

class CetaVmBoundaryTests(unittest.TestCase):
    def test_network_cannot_supply_proof(self):
        with self.assertRaises(ProposalBindingError):
            TransitionProposal.from_mapping({
                'input_state_ref':'S0','operation':'Observe','operands':{},'proposer_id':'model',
                'proof': {'claimed':'self-certified'}
            })

    def test_unknown_opcode_halts(self):
        p=TransitionProposal.from_mapping({'input_state_ref':'S0','operation':'InventTruth','operands':{},'proposer_id':'model'})
        d=ConstitutionalVM().evaluate(p, projected_state_ref='S0')
        self.assertEqual(d.disposition, VmDisposition.HALT)
        self.assertEqual(d.reason_code,'UNKNOWN_CETA_OPCODE')

    def test_state_reference_mismatch_halts_before_opcode(self):
        p=TransitionProposal.from_mapping({'input_state_ref':'STALE','operation':'Observe','operands':{},'proposer_id':'model'})
        d=ConstitutionalVM().evaluate(p, projected_state_ref='CURRENT')
        self.assertEqual(d.reason_code,'INPUT_STATE_REFERENCE_MISMATCH')

    def test_bound_opcode_requires_full_projected_snapshot(self):
        p=TransitionProposal.from_mapping({'input_state_ref':'S0','operation':'Observe','operands':{},'proposer_id':'model'})
        d=ConstitutionalVM().evaluate(p, projected_state_ref='S0')
        self.assertEqual(d.reason_code,'PROJECTED_STATE_SNAPSHOT_REQUIRED')

    def test_extra_proposal_fields_fail_binding(self):
        with self.assertRaises(ProposalBindingError):
            TransitionProposal.from_mapping({'input_state_ref':'S0','operation':'Observe','operands':{},'proposer_id':'model','explanation':'trust me'})

if __name__=='__main__': unittest.main()
