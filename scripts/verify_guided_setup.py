"""Exercise native guided offline import and restart using actual pinned assets.

Runs source CETA in a new isolated data directory with synthetic probe prompts.
Download transports are forbidden; this does not establish OS network isolation.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-zip", type=Path, required=True)
    parser.add_argument("--model-zip", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--screenshot", type=Path)
    parser.add_argument("--measure", action="store_true", help="Explicitly run the seven-request capability suite through its native button")
    args = parser.parse_args()
    if os.name != "nt" or args.data_dir.exists() or args.report.exists() or (args.screenshot and args.screenshot.exists()):
        parser.error("Use Windows and new data, report and screenshot paths; existing files are preserved")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QProcess
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication, QScrollArea
    from ceta_desktop.app import MainWindow
    from ceta_desktop.model_installation import ManagedModels
    from ceta_desktop.runtime_installation import RuntimeInstallation
    from verify_desktop_runtime import source_attribution
    before = source_attribution()
    report = {"schema":"ceta.guided-setup-verification.v1", "passed":False, "source_before":before,
              "scope":"Native source UI, real pinned runtime/model, synthetic probes, explicit offline archives and restart",
              "os_network_isolation":False, "frozen_application":False, "download_transports_forbidden":True,
              "file_dialog_inputs":"Explicit command-line archive paths; no runtime or generation mocks", "steps":[]}
    app = QApplication.instance() or QApplication([])
    QFontDatabase.addApplicationFont(r"C:\Windows\Fonts\segoeui.ttf")
    window = None

    def wait(predicate, timeout=300):
        deadline = time.monotonic()+timeout
        while not predicate() and time.monotonic()<deadline:
            app.processEvents(); time.sleep(.01)
        app.processEvents()
        if not predicate():
            raise TimeoutError(window.guided_setup.status.text() if window else "Native setup wait expired")

    def close():
        if window.guided_setup.busy:
            window.guided_setup.pause()
        for task in window.tasks:
            task.cancelled.set()
        wait(lambda: not window.tasks and not window.guided_setup.busy)
        window.editor.document().setModified(False)
        if not window.close():
            wait(lambda: window.model_process.state() == QProcess.NotRunning, 10)
            if not window.close():
                raise RuntimeError("Native window did not close")
        observation = window.model_process.last_observation
        if observation and observation.get("active_processes") != 0:
            raise RuntimeError("Owned workers did not confirm shutdown")
        window.deleteLater(); app.processEvents()
        return observation

    try:
        with patch("ceta_desktop.runtime_installation._open_release", side_effect=AssertionError("Unexpected runtime download")), \
                patch("ceta_desktop.model_installation._open_blob", side_effect=AssertionError("Unexpected model download")):
            window = MainWindow(args.data_dir)
            window.resize(1440,1080); window.show()
            if window.guided_setup.profile is not None or window.guided_setup.tested_selection is not None:
                raise RuntimeError("Fresh setup unexpectedly has readiness")
            window.open_local_setup()
            wait(lambda: not window.tasks and not window.guided_setup.busy)
            panel = window.guided_setup
            report["hardware"] = asdict(panel.profile)
            index = panel.choice.findData(args.model)
            if index < 0:
                raise RuntimeError("The requested model is not one of this computer's guided candidates")
            panel.choice.setCurrentIndex(index)
            if not panel.offline_button.isEnabled():
                raise RuntimeError("This computer did not admit the selected candidate")
            with patch("ceta_desktop.pages.local_setup.QFileDialog.getOpenFileName", side_effect=[(str(args.runtime_zip.resolve()),"ZIP"),(str(args.model_zip.resolve()),"ZIP")]):
                panel.offline_button.click()
            wait(lambda: not window.tasks and not panel.busy, 900)
            if panel.stage != "tested" or not panel.test_result:
                raise RuntimeError(panel.status.text())
            report["steps"].append({"operation":"offline_import_and_test", "result":panel.test_result, "status":panel.status.text()})
            report["runtime"] = RuntimeInstallation(args.data_dir).verify()
            report["model"] = ManagedModels(args.data_dir).verify(args.model)
            if args.measure:
                capabilities = window.capabilities_panel
                if capabilities.report is not None:
                    raise RuntimeError("Setup ran an undisclosed capability measurement")
                capabilities.measure_button.click()
                wait(lambda: not window.tasks and capabilities.task is None, 1320)
                measured = capabilities.report
                if not measured or measured["status"] != "completed" or capabilities.bound is None:
                    raise RuntimeError(capabilities.status.text() + " " + capabilities.results.toPlainText())
                report["steps"].append({"operation": "native_capability_measurement", "result": measured,
                                        "display": capabilities.results.toPlainText()})
                for scroll in window.findChildren(QScrollArea):
                    if scroll.isAncestorOf(capabilities):
                        scroll.ensureWidgetVisible(capabilities)
            if args.screenshot:
                for _ in range(30):app.processEvents(); time.sleep(.01)
                if not window.grab().save(str(args.screenshot)):
                    raise RuntimeError("Native screenshot failed")
            report["steps"].append({"operation":"close", "result":close()})
            window = MainWindow(args.data_dir)
            window.show()
            panel = window.guided_setup
            if panel.test_result is not None or panel.tested_selection is not None or panel.profile is not None:
                raise RuntimeError("Restart restored live readiness")
            if window.capabilities_panel.bound is not None or window.capabilities_panel.report is not None:
                raise RuntimeError("Restart restored a live capability observation")
            report["steps"].append({"operation":"restart", "readiness_restored":False,
                                     "saved_model_choice":window.store.setting("managed_model_id")})
            window.open_local_setup()
            wait(lambda: not window.tasks and not panel.busy)
            if panel.choice.currentData() != args.model:
                raise RuntimeError("Saved model preference was not retained")
            panel.recheck_button.click()
            wait(lambda: not window.tasks and not panel.busy)
            if panel.stage != "tested" or not panel.test_result:
                raise RuntimeError(panel.status.text())
            report["steps"].append({"operation":"recheck_and_test", "result":panel.test_result})
            if args.measure:
                window.capabilities_panel.history_button.click()
                wait(lambda: not window.tasks)
                if window.capabilities_panel.bound is not None or "Historical" not in window.capabilities_panel.results.toPlainText():
                    raise RuntimeError("Saved measurement was not presented as historical")
                report["steps"].append({"operation": "capability_history_after_restart", "live_readiness": False,
                                        "display": window.capabilities_panel.results.toPlainText()})
            report["steps"].append({"operation":"close", "result":close()})
            window = None
            report["passed"] = True
    except Exception as exc:
        report["error"] = str(exc)
    finally:
        if window is not None:
            try:
                report["cleanup"] = close()
            except Exception as exc:
                report["cleanup_error"] = str(exc)
                report["passed"] = False
        after = source_attribution()
        report["source_after_sha256"] = after["source_sha256"]
        report["source_unchanged"] = after["source_sha256"] == before["source_sha256"]
        report["passed"] = report["passed"] and report["source_unchanged"]
        with args.report.open("x",encoding="utf-8") as output:
            json.dump(report,output,indent=2,ensure_ascii=False)
        print(json.dumps({key:report[key] for key in ("passed","source_after_sha256","source_unchanged")},ensure_ascii=False))
        if not report["passed"]:
            print(report.get("error",report.get("cleanup_error","Source changed during verification")))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
