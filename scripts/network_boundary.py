"""Explicit desktop transport boundary; the reference runtime remains no-fetch."""
from __future__ import annotations

import ast


DESKTOP_TRANSPORT_IMPORTS = {
    "src/ceta_desktop/models.py": {"http.client", "socket"},
    "src/ceta_desktop/updates.py": {"urllib.request"},
}
NETWORK_ROOTS = {"requests", "httpx", "socket", "github", "gitlab"}


def network_import_errors(tree: ast.AST, relative: str) -> list[str]:
    errors = []
    allowed = DESKTOP_TRANSPORT_IMPORTS.get(relative, set())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
            if node.module in {"http", "urllib"}:
                names.extend(f"{node.module}.{alias.name}" for alias in node.names)
        else:
            continue
        for name in names:
            capable = name.split(".", 1)[0] in NETWORK_ROOTS or name.startswith(("urllib.request", "http.client"))
            if capable and name not in allowed:
                errors.append(f"network-capable import outside declared desktop transports: {relative} -> {name}")
    return errors
