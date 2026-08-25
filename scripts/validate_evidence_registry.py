from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
resp = {x["id"] for x in json.loads((ROOT / "registry/responsibilities.json").read_text()) ["responsibilities"]}
source_doc = json.loads((ROOT / "registry/source_registry.json").read_text())
sources_list = source_doc["sources"]
sources = {x["id"] for x in sources_list}
source_by_id = {x["id"]: x for x in sources_list}
manifest = json.loads((ROOT / "corpus/local_file_manifest.json").read_text())
manifest_by_key = {(x["root"], x["relative_path"]): x for x in manifest["files"]}
errors: list[str] = []

if source_doc.get("access_policy", {}).get("network_access") != "PROHIBITED":
    errors.append("source registry must prohibit network access")
if source_doc.get("access_policy", {}).get("remote_fetch_on_verify") is not False:
    errors.append("source verification may not fetch remote content")

for source in sources_list:
    if source.get("kind") == "frozen_remote_source_metadata":
        if source.get("access") != "NO_FETCH" or source.get("status") != "frozen_reference":
            errors.append(f"remote source not frozen/no-fetch: {source['id']}")
    if source.get("kind") == "local_manifest_file":
        key = (source.get("manifest_root"), source.get("path"))
        item = manifest_by_key.get(key)
        if item is None:
            errors.append(f"local source missing from corpus manifest: {source['id']}")
        elif item.get("sha256") != source.get("sha256"):
            errors.append(f"local source hash mismatch against corpus manifest: {source['id']}")

assertions = json.loads((ROOT / "registry/source_assertions.json").read_text())["assertions"]
for assertion in assertions:
    if assertion["source"] not in sources:
        errors.append(f"unknown source {assertion['source']}")
    for responsibility in assertion["maps_to"]:
        if responsibility not in resp:
            errors.append(f"assertion maps to unknown responsibility {responsibility}")

queue = json.loads((ROOT / "registry/legacy_admission_queue.json").read_text())["items"]
for item in queue:
    if item["candidate_responsibility"] not in resp:
        errors.append(f"legacy item has unknown responsibility {item['legacy']}")
    if item["decision"] not in {"PORT", "REWRITE", "FIXTURE_ONLY", "RESEARCH_ONLY", "REJECT", "UNRESOLVED"}:
        errors.append(f"invalid decision {item['legacy']}: {item['decision']}")

owners = {x["owner"] for x in json.loads((ROOT / "registry/responsibilities.json").read_text())["responsibilities"]}
failures = json.loads((ROOT / "evidence/historical_failures.json").read_text())["failures"]
for failure in failures:
    if failure["fixture_target"] not in owners:
        errors.append(f"historical failure target is not a canonical owner: {failure['fixture_target']}")

conflicts = json.loads((ROOT / "evidence/ownership_conflicts.json").read_text())["conflicts"]
for conflict in conflicts:
    adjudication = ROOT / "evidence" / "adjudications" / f"{conflict['id']}_{conflict['responsibility']}.json"
    # OC-001..004 use historical descriptive filenames, so fall back to id prefix.
    if not adjudication.exists():
        matches = list((ROOT / "evidence" / "adjudications").glob(f"{conflict['id']}_*.json"))
        if not matches:
            errors.append(f"ownership conflict lacks adjudication record: {conflict['id']}")

if errors:
    print("EVIDENCE REGISTRY: FAIL")
    for error in errors:
        print(" -", error)
    raise SystemExit(1)
print("EVIDENCE REGISTRY: PASS")
print(f"sources={len(sources)} assertions={len(assertions)} historical_failures={len(failures)} ownership_conflicts={len(conflicts)}")
