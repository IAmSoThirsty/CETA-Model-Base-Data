"""One process-bound monotonic time budget for a prepared local request."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import math
import time
from uuid import uuid4


class ModelError(ValueError):
    pass


class ModelDeadlineError(ModelError, TimeoutError):
    pass


class ModelCancelledError(ModelError):
    pass


_ORIGIN = uuid4().hex
_CURRENT = ContextVar("ceta_request_budget", default=None)


class RequestBudget:
    def __init__(self, seconds, cancelled=None, receipt=None):
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 < seconds <= 3600:
            raise ValueError("Request time limit must be greater than zero and at most 3600 seconds.")
        self.seconds, self.cancelled = seconds, cancelled
        self.started = time.monotonic()
        self.deadline = self.started + seconds
        if receipt is not None:
            if (not isinstance(receipt, dict) or set(receipt) != {"origin", "started", "deadline", "seconds"} or
                    receipt["origin"] != _ORIGIN or receipt["seconds"] != seconds or
                    any(type(receipt[key]) not in (int, float) or not math.isfinite(receipt[key])
                        for key in ("started", "deadline", "seconds")) or
                    receipt["started"] > self.started or
                    abs(receipt["deadline"] - receipt["started"] - seconds) > 0.000001):
                raise ModelError("The request time budget changed or belongs to an earlier app session. Prepare again.")
            self.started, self.deadline = receipt["started"], receipt["deadline"]

    def receipt(self):
        return {"origin": _ORIGIN, "started": self.started, "deadline": self.deadline, "seconds": self.seconds}

    def check(self):
        if time.monotonic() >= self.deadline:
            raise ModelDeadlineError("The complete request exceeded its time limit. Prepare a new request; retry material is retained.")
        if self.cancelled is not None:
            check = getattr(self.cancelled, "is_set", self.cancelled)
            if check() if callable(check) else bool(check):
                raise ModelCancelledError("Request stopped; retry material is retained.")


def current_budget():
    return _CURRENT.get()


def checkpoint():
    budget = current_budget()
    if budget is not None:
        budget.check()


def deadline_limit(deadline):
    budget = current_budget()
    return min(deadline, budget.deadline) if budget is not None else deadline


@contextmanager
def request_scope(seconds=180, cancelled=None, receipt=None):
    budget = current_budget()
    if budget is not None:
        if seconds != budget.seconds or (receipt is not None and receipt != budget.receipt()):
            raise ModelError("The request time budget changed within the active request.")
        budget.check()
        yield budget
        return
    budget = RequestBudget(seconds, cancelled, receipt)
    budget.check()
    token = _CURRENT.set(budget)
    try:
        yield budget
    finally:
        _CURRENT.reset(token)
