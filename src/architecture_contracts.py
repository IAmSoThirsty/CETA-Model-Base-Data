from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class ArchitectureError(RuntimeError):
    pass

def load_json(name: str):
    return json.loads((ROOT / 'registry' / name).read_text(encoding='utf-8'))

def validate() -> list[str]:
    errors: list[str] = []
    components = load_json('components.json')['components']
    responsibilities = load_json('responsibilities.json')['responsibilities']
    operations = load_json('ceta_operations.json')

    component_by_id = {c['id']: c for c in components}
    if len(component_by_id) != len(components):
        errors.append('duplicate component id')

    seen_resp: set[str] = set()
    for r in responsibilities:
        if r['id'] in seen_resp:
            errors.append(f"duplicate responsibility: {r['id']}")
        seen_resp.add(r['id'])
        if r['owner'] not in component_by_id:
            errors.append(f"orphan responsibility {r['id']}: unknown owner {r['owner']}")

    # Constitutional separations.
    proposers = [c for c in components if c.get('may_propose')]
    for c in proposers:
        if c.get('may_authorize') or c.get('may_execute') or c.get('may_commit_state') or c.get('may_verify_effect'):
            errors.append(f"proposal component has forbidden authority: {c['id']}")

    authorities = [c for c in components if c.get('may_authorize')]
    for c in authorities:
        if c.get('may_execute') or c.get('may_verify_effect'):
            errors.append(f"authority component crosses effect boundary: {c['id']}")

    executors = [c for c in components if c.get('may_execute')]
    for c in executors:
        if c.get('may_authorize') or c.get('may_verify_effect') or c.get('may_commit_state'):
            errors.append(f"executor self-authorizes/self-certifies/commits state: {c['id']}")

    canonical_committers = [c['id'] for c in components if c.get('may_commit_state')]
    if canonical_committers != ['transition_ledger']:
        errors.append(f'canonical state committers must equal [transition_ledger], got {canonical_committers}')

    state_owner = next((r['owner'] for r in responsibilities if r['id'] == 'current_state_projection'), None)
    if state_owner != 'state_projector':
        errors.append('current state projection must be owned by state_projector')
    if component_by_id.get('state_projector', {}).get('may_commit_state'):
        errors.append('state projector may not commit canonical state')

    expected_ops = {
        'Observe','ValidateObservation','AdmitEvidence','RejectEvidence','CreateClaim','CreateBelief',
        'Support','Contradict','Undercut','Merge','Split','NarrowScope','ExpandScope','Verify',
        'Invalidate','Suspend','Expire','Reevaluate','Adjudicate','Authorize','RejectAuthorization',
        'Execute','Rollback'
    }
    actual_ops = set(operations.get('operations', []))
    if actual_ops != expected_ops:
        errors.append(f'CETA operation set mismatch: missing={sorted(expected_ops-actual_ops)} extra={sorted(actual_ops-expected_ops)}')


    # Every declared owner must have an explicit local implementation path.
    implementation = load_json('implementation_map.json')['implementations']
    impl_by_component = {x['component']: x for x in implementation}
    if len(impl_by_component) != len(implementation):
        errors.append('duplicate implementation map component')
    for component_id in component_by_id:
        item = impl_by_component.get(component_id)
        if item is None:
            errors.append(f'missing implementation mapping: {component_id}')
            continue
        for rel in item.get('paths', []):
            if not (ROOT / rel).is_file():
                errors.append(f'implementation path missing for {component_id}: {rel}')

    # All CETA opcodes must have one bound executable contract.
    contracts = load_json('operation_contracts.json')['contracts']
    contract_ops = [x.get('operation') for x in contracts]
    if len(contract_ops) != len(set(contract_ops)):
        errors.append('duplicate CETA operation contract')
    if set(contract_ops) != expected_ops:
        errors.append(f'CETA contract set mismatch: missing={sorted(expected_ops-set(contract_ops))} extra={sorted(set(contract_ops)-expected_ops)}')
    for contract in contracts:
        if contract.get('status') != 'BOUND':
            errors.append(f"CETA operation contract not bound: {contract.get('operation')}")
        if not contract.get('preconditions') or not contract.get('postconditions') or not contract.get('constitutional_constraints') or not contract.get('proof_obligations'):
            errors.append(f"CETA operation contract incomplete: {contract.get('operation')}")

    constraints = load_json('build_constraints.json')['constraints']
    if constraints.get('offline_build') is not True or constraints.get('remote_runtime_dependencies') is not False:
        errors.append('build must remain offline with no remote runtime dependency')
    if constraints.get('legacy_api_compatibility_required') is not False:
        errors.append('legacy compatibility may not constrain clean architecture')
    if constraints.get('source_network_access') != 'PROHIBITED':
        errors.append('source network access must be prohibited')
    for key in (
        'caller_authored_authority_context_allowed',
        'remote_runtime_dependencies',
        'legacy_repository_imports_allowed',
    ):
        if constraints.get(key) is not False:
            errors.append(f'constraint must be false: {key}')
    for key in (
        'effect_transition_reservation_before_commit',
        'signed_effect_invocation_required',
        'signed_independent_effect_observation_required',
        'durable_proof_registries_required',
    ):
        if constraints.get(key) is not True:
            errors.append(f'constraint must be true: {key}')

    boundary = operations.get('proposal_boundary', {})
    forbidden_network_outputs = {'output_state_ref','proof','verification','replay_record'}
    if forbidden_network_outputs & set(boundary.get('network_outputs', [])):
        errors.append('network output boundary contains VM-owned fields')

    return errors

def assert_valid() -> None:
    errors = validate()
    if errors:
        raise ArchitectureError('\n'.join(errors))
