from __future__ import annotations

import ast
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from training import ReferenceCurriculum

errors: list[str] = []

# No executable network client imports in this release.
blocked_roots = {"requests", "httpx", "socket", "github", "gitlab"}
for base in (ROOT / "src", ROOT / "scripts", ROOT / "examples"):
    for path in sorted(base.rglob("*.py")):
        if path.name == "hostile_audit.py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            errors.append(f"syntax error {path.relative_to(ROOT)}: {exc}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [x.name for x in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                root = name.split(".", 1)[0]
                if root in blocked_roots or name.startswith("urllib.request") or name.startswith("http.client"):
                    errors.append(f"network-capable import in executable source: {path.relative_to(ROOT)} -> {name}")


# Do not ship literal private keys or common credential assignments.
secret_markers = ("-----BEGIN " + "PRIVATE KEY-----", "-----BEGIN OPENSSH " + "PRIVATE KEY-----", "AWS_SECRET_ACCESS" + "_KEY=", "GITHUB" + "_TOKEN=", "OPENAI_API" + "_KEY=")
for base in (ROOT / "src", ROOT / "scripts", ROOT / "examples", ROOT / "registry", ROOT / "evidence", ROOT / "docs", ROOT / "spec"):
    if not base.exists():
        continue
    for path in sorted(x for x in base.rglob("*") if x.is_file() and x.suffix in {".py", ".json", ".md", ".txt"}):
        text = path.read_text(encoding="utf-8", errors="replace")
        for marker in secret_markers:
            if marker in text:
                errors.append(f"literal credential/private-key material in package source: {path.relative_to(ROOT)}")

# Embedded source verification must remain no-fetch.
source_registry = json.loads((ROOT / "registry/source_registry.json").read_text(encoding="utf-8"))
policy = source_registry.get("access_policy", {})
if policy.get("network_access") != "PROHIBITED" or policy.get("remote_fetch_on_verify") is not False:
    errors.append("source registry does not enforce local-only verification")
for source in source_registry.get("sources", []):
    if source.get("kind") == "frozen_remote_source_metadata" and source.get("access") != "NO_FETCH":
        errors.append(f"frozen remote source is fetch-enabled: {source.get('id')}")

# No unresolved ownership or legacy admission decisions.
queue = json.loads((ROOT / "registry/legacy_admission_queue.json").read_text(encoding="utf-8"))["items"]
if any(x.get("decision") == "UNRESOLVED" for x in queue):
    errors.append("unresolved legacy admission remains")
conflicts = json.loads((ROOT / "evidence/ownership_conflicts.json").read_text(encoding="utf-8"))["conflicts"]
for conflict in conflicts:
    if not list((ROOT / "evidence/adjudications").glob(f"{conflict['id']}_*.json")):
        errors.append(f"ownership conflict lacks adjudication: {conflict['id']}")

# Runtime API must not expose the old caller-authored authority snapshot path.
runtime_path = ROOT / "src/runtime/core.py"
runtime_text = runtime_path.read_text(encoding="utf-8")
runtime_tree = ast.parse(runtime_text, filename=str(runtime_path))
for node in ast.walk(runtime_tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in {"evaluate", "commit"}:
        public_args = {arg.arg for arg in (*node.args.args, *node.args.kwonlyargs)}
        if "authority_snapshot" in public_args:
            errors.append(f"runtime public API {node.name} exposes caller-authored authority_snapshot")
if "authority_assertion" not in runtime_text:
    errors.append("runtime lacks signed authority assertion boundary")

# Effect adapters must require the signed gateway invocation.
adapter_text = (ROOT / "src/tool_adapters/adapters.py").read_text(encoding="utf-8")
for marker in ("GatewayInvocation", "verify_gateway_invocation", "gateway invocation signature invalid"):
    if marker not in adapter_text:
        errors.append(f"adapter gateway binding missing marker: {marker}")

# Durable proof registries must fsync writes and replay on initialization.
for rel in ("src/evidence_registry/registry.py", "src/identity_registry/registry.py", "src/authority/ledger.py"):
    text = (ROOT / rel).read_text(encoding="utf-8")
    if "os.fsync" not in text:
        errors.append(f"durable registry does not fsync: {rel}")
    if "_load" not in text:
        errors.append(f"durable registry lacks replay loader: {rel}")

# Neural curriculum may not contain language-answer targets.
for case in ReferenceCurriculum().build():
    record = case.to_record()
    forbidden = {"prompt", "response", "expected_output", "answer", "completion"} & set(record)
    if forbidden:
        errors.append(f"language target leaked into training record {case.case_id}: {sorted(forbidden)}")
    target = record.get("target_transition", {})
    if set(target) != {"input_state_ref", "operation", "operands", "proposer_id"}:
        errors.append(f"training target boundary mismatch: {case.case_id}")

# VM operation contracts must all be bound and one-to-one.
ops = set(json.loads((ROOT / "registry/ceta_operations.json").read_text(encoding="utf-8"))["operations"])
contracts = json.loads((ROOT / "registry/operation_contracts.json").read_text(encoding="utf-8"))["contracts"]
contract_ops = [x.get("operation") for x in contracts]
if set(contract_ops) != ops or len(contract_ops) != len(set(contract_ops)):
    errors.append("CETA operation-to-contract mapping is not one-to-one")
if any(x.get("status") != "BOUND" for x in contracts):
    errors.append("one or more CETA operation contracts are unbound")

if errors:
    print("HOSTILE AUDIT: FAIL")
    for error in errors:
        print(" -", error)
    raise SystemExit(1)
print("HOSTILE AUDIT: PASS")
print(f"checks=local_only,ownership,authority,effects,durability,training,ceta_contracts conflicts={len(conflicts)}")
