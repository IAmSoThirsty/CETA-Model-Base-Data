"""Qt event-loop adapter for the owned Windows model runtime."""
from __future__ import annotations

import time

from PySide6.QtCore import QByteArray, QObject, QProcess, QProcessEnvironment, QTimer, Signal

from .runtime_coordination import RuntimeLease
from .windows_job import WindowsJobProcess


class OwnedModelProcess(QObject):
    readyReadStandardOutput = Signal()
    started = Signal()
    errorOccurred = Signal(object)
    finished = Signal(int, object)

    def __init__(self, parent=None, *, coordination_directory=None):
        super().__init__(parent)
        self._program, self._arguments = "", []
        self._environment = QProcessEnvironment.systemEnvironment()
        self._state = QProcess.NotRunning
        self._error, self._output = "", bytearray()
        self._process = None
        self._endpoint = None
        self.coordination_directory = coordination_directory
        self.last_observation = None
        self.containment = None
        self.managed_assets = None
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._poll)

    def setProcessChannelMode(self, mode):
        if mode != QProcess.MergedChannels:
            raise ValueError("Owned model output uses merged channels.")

    def setProgram(self, program):
        self._program = str(program)

    def program(self):
        return self._program

    def setArguments(self, arguments):
        self._arguments = list(arguments)

    def arguments(self):
        return list(self._arguments)

    def setProcessEnvironment(self, environment):
        self._environment = QProcessEnvironment(environment)

    def processEnvironment(self):
        return QProcessEnvironment(self._environment)

    def setEndpoint(self, host, port):
        self._endpoint = (host, port)

    def state(self):
        return self._state

    def processId(self):
        return self._process.pid if self._process is not None else 0

    def errorString(self):
        return self._error

    def setManagedAssets(self, assets):
        if self._state != QProcess.NotRunning:
            raise ValueError("Stop the owned workers before replacing their protected assets.")
        if self.managed_assets is assets:
            return
        self.releaseManagedAssets()
        self.managed_assets = assets

    def releaseManagedAssets(self):
        if self._state != QProcess.NotRunning:
            raise ValueError("Protected assets stay held until owned shutdown is confirmed.")
        if self.managed_assets is not None:
            self.managed_assets.close()
            self.managed_assets = None

    def start(self):
        if self._state != QProcess.NotRunning:
            raise ValueError("The owned model runtime is already running.")
        if self._endpoint is None:
            raise ValueError("Owned startup requires an explicit local endpoint.")
        self._state = QProcess.Starting
        self._error, self._output, self.last_observation = "", bytearray(), None
        self.containment = None
        try:
            with RuntimeLease(*self._endpoint, directory=self.coordination_directory, allow_uncertain=True) as lease:
                lease.prepare_owned_start()
                self._process = WindowsJobProcess()
                if self.managed_assets is not None:
                    self.managed_assets.assert_runtime(self._program)
                environment = {key: self._environment.value(key) for key in self._environment.keys()}
                def registered(process):
                    lease.register_owned(process)
                    if self.managed_assets is not None:
                        self.managed_assets.bind_job(process.name)
                self._process.start(self._program, self._arguments, environment, registered)
                self.containment = dict(lease.record["owned_runtime"])
            self._state = QProcess.Running
            self._timer.start()
            self.started.emit()
        except (OSError, ValueError, RuntimeError) as exc:
            if self._process is not None:
                self._process.close()
                self._process = None
            self._state = QProcess.NotRunning
            self.releaseManagedAssets()
            self._error = str(exc)
            self.errorOccurred.emit(QProcess.FailedToStart)

    def readAllStandardOutput(self):
        output, self._output = self._output, bytearray()
        return QByteArray(bytes(output))

    def kill(self):
        if self._process is not None:
            self._process.stop()

    def _poll(self):
        if self._process is None:
            return
        try:
            output = self._process.read()
            if output:
                # Bound retained output even when there is no connected reader.
                self._output.extend(output)
                del self._output[:-1024 * 1024]
                self.readyReadStandardOutput.emit()
            code = self._process.poll()
            if code is None:
                return
            self.last_observation = self._process.last_observation
            status = QProcess.CrashExit if self._process.killed else QProcess.NormalExit
            self._process.close()
            self._process = None
            self._state = QProcess.NotRunning
            self.releaseManagedAssets()
            self._timer.stop()
            # Windows status values are unsigned DWORDs; Qt's signal is signed.
            code = code if code < 2**31 else code - 2**32
            self.finished.emit(code, status)
        except (OSError, ValueError) as exc:
            message = f"Owned runtime shutdown is unconfirmed: {exc}"
            if self._error != message:
                self._error = message
                self.errorOccurred.emit(QProcess.UnknownError)
            # Keep ownership and retry observation. Never turn query failure into
            # a finished signal or silently release an uncertain worker group.

    def waitForFinished(self, milliseconds=30000):
        deadline = time.monotonic() + max(0, milliseconds) / 1000
        while self._state != QProcess.NotRunning and time.monotonic() < deadline:
            self._poll()
            if self._state != QProcess.NotRunning:
                time.sleep(0.01)
        return self._state == QProcess.NotRunning
