"""Exercise native chat against an explicitly selected, already installed model."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from ceta_desktop.app import MainWindow
from ceta_desktop.models import LocalModelClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or output.is_relative_to(ROOT):
        raise SystemExit("Use a new output directory outside the repository.")
    if args.model not in LocalModelClient(args.endpoint).available_models():
        raise SystemExit("The selected model is not installed in the selected local service.")
    output.mkdir(parents=True)
    app = QApplication.instance() or QApplication([])
    window = MainWindow(output / "application-data")
    window.show()
    window.endpoint.setText(args.endpoint)
    window.model_combo.setCurrentText(args.model)
    window.prompt.setPlainText("Reply with exactly LOCAL_OK. /no_think")
    started = time.monotonic()
    window.send_message()
    while window.chat_task and time.monotonic() - started < 180:
        QTest.qWait(50)
    if window.chat_task:
        window.stop_chat()
        deadline = time.monotonic() + 15
        while window.chat_task and time.monotonic() < deadline:
            QTest.qWait(50)
    if window.chat_task:
        raise RuntimeError("The native chat worker did not stop within its cancellation deadline.")
    elapsed = time.monotonic() - started
    identifier = window.conversation_id
    before = window.store.messages(identifier)
    window.grab().save(str(output / "real-inference-window.png"))
    window.close()
    app.processEvents()
    reopened = MainWindow(output / "application-data")
    after = reopened.store.messages(identifier)
    reopened.close()
    passed = bool(before and before[-1]["status"] == "complete" and before[-1]["content"].strip() == "LOCAL_OK" and before == after)
    result = {"created_at": datetime.now(timezone.utc).isoformat(), "status": "PASS" if passed else "FAIL",
              "model": args.model, "transport": "loopback", "duration_seconds": round(elapsed, 3),
              "messages": before, "restart_persistence": before == after,
              "claim": "integration_smoke_only_not_model_quality_benchmark"}
    (output / "real-inference-result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
