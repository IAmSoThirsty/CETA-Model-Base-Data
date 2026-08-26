import copy, sys, unittest
from pathlib import Path
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
import architecture_contracts as ac

class ArchitectureContractTests(unittest.TestCase):
    def test_current_registry_passes(self):
        self.assertEqual(ac.validate(), [])

    def _mutated_validate(self, name, mutate):
        original = ac.load_json
        def fake_load(n):
            value = copy.deepcopy(original(n))
            if n == name:
                mutate(value)
            return value
        with patch.object(ac, 'load_json', side_effect=fake_load):
            return ac.validate()

    def test_duplicate_responsibility_fails(self):
        errors = self._mutated_validate('responsibilities.json', lambda x: x['responsibilities'].append(copy.deepcopy(x['responsibilities'][0])))
        self.assertTrue(any('duplicate responsibility' in e for e in errors))

    def test_orphan_owner_fails(self):
        errors = self._mutated_validate('responsibilities.json', lambda x: x['responsibilities'][0].__setitem__('owner','missing'))
        self.assertTrue(any('orphan responsibility' in e for e in errors))

    def test_model_authority_fails(self):
        def mutate(x):
            next(c for c in x['components'] if c['id']=='transition_policy_model')['may_authorize'] = True
        errors = self._mutated_validate('components.json', mutate)
        self.assertTrue(any('proposal component has forbidden authority' in e for e in errors))

    def test_executor_self_verification_fails(self):
        def mutate(x):
            next(c for c in x['components'] if c['id']=='effect_gateway')['may_verify_effect'] = True
        errors = self._mutated_validate('components.json', mutate)
        self.assertTrue(any('executor self-authorizes' in e for e in errors))

    def test_second_state_committer_fails(self):
        def mutate(x):
            next(c for c in x['components'] if c['id']=='memory_projection')['may_commit_state'] = True
        errors = self._mutated_validate('components.json', mutate)
        self.assertTrue(any('canonical state committers' in e for e in errors))

    def test_network_cannot_output_vm_owned_proof(self):
        def mutate(x):
            x['proposal_boundary']['network_outputs'].append('proof')
        errors = self._mutated_validate('ceta_operations.json', mutate)
        self.assertTrue(any('VM-owned fields' in e for e in errors))

if __name__ == '__main__': unittest.main()
