"""Compare uncached and bounded-cache journal reads on one unchanged SQLite snapshot.

Use a synthetic verification profile. Opens the source read-only; exports no event
payloads. This measures journal read latency, not model speed or UI responsiveness.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.report.exists() or not 1 <= args.repeats <= 20:
        parser.error("Use a new report path and 1-20 repeats")
    import runtime.journal as module
    from verify_desktop_runtime import source_attribution
    before = source_attribution()
    journal = module.Journal(args.database.resolve(), read_only=True)
    report = {"schema": "ceta.journal-read-profile.v1", "source_before": before,
              "scope": __doc__, "passed": False, "database": str(args.database.resolve()), "modes": []}
    try:
        # One read transaction pins the same SQLite snapshot for both modes. An
        # independent writer cannot change the dataset underneath this comparison.
        with journal.transaction():
            streams = [dict(row) for row in journal.db.execute(
                "SELECT project_id,sequence,head FROM project_streams ORDER BY project_id")]
            task = journal.db.execute("SELECT task_id,project_id FROM project_tasks ORDER BY last_sequence DESC LIMIT 1").fetchone()
            if task is None:
                raise ValueError("The synthetic profile needs at least one canonical task")
            report["streams"] = streams
            for mode, limit in (("uncached", 0), ("bounded_cache", module.VERIFIED_ROW_COUNT)):
                journal._verified_rows.clear()
                journal._verified_row_bytes = 0
                hash_count = 0
                original = module.digest

                def counted(value):
                    nonlocal hash_count
                    hash_count += 1
                    return original(value)

                with patch.object(module, "VERIFIED_ROW_COUNT", limit), patch.object(module, "digest", counted):
                    samples = []
                    for _ in range(args.repeats):
                        start = time.perf_counter()
                        journal.task(task["task_id"])
                        journal.events(task["project_id"], task_id=task["task_id"])
                        journal.head(task["project_id"])
                        samples.append(time.perf_counter() - start)
                report["modes"].append({"mode": mode, "seconds": samples,
                    "total_seconds": sum(samples), "event_hash_calculations": hash_count,
                    "retained_rows": len(journal._verified_rows), "row_budget_bytes": journal._verified_row_bytes})
            report["snapshot_unchanged"] = streams == [dict(row) for row in journal.db.execute(
                "SELECT project_id,sequence,head FROM project_streams ORDER BY project_id")]
            report["passed"] = report["snapshot_unchanged"] and report["modes"][1]["event_hash_calculations"] < report["modes"][0]["event_hash_calculations"]
    finally:
        journal.close()
    after = source_attribution()
    report["source_after_sha256"] = after["source_sha256"]
    report["source_unchanged"] = before["source_sha256"] == after["source_sha256"]
    report["passed"] = report["passed"] and report["source_unchanged"]
    with args.report.open("x", encoding="utf-8") as output:
        json.dump(report, output, indent=2)
        output.write("\n")
    print(json.dumps({key: report[key] for key in ("passed", "modes", "source_unchanged")}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
