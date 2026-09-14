# Contributing to CETA

Welcome to the CETA project repository. CETA is both the reference native desktop application and the Constitutional Epistemic Transition Algebra reference core.

Please review this guide before proposing or submitting changes.

---

## 1. Project Boundaries and Isolation

Apply the project rules defined in `AGENTS.md` and `T:\PROJECT_ISOLATION_RULEBOOK.md`:
- Do not mix code, branding, paths, documentation, or evidence from another project into CETA without express user authorization.
- Earlier artifact names, hashes, and release outputs remain immutable historical records.
- Check current source, documentation, packaging, and outputs for unintended project crossover.
- Read `docs/operations/CONTINUITY_MAP.md` when continuing work and record actual changes, validation, and remaining issues there.

---

## 2. Prerequisites & Environment Setup

- **Python**: 3.12+ (compatible with Python >= 3.11, < 3.14).
- **Package Manager**: `uv` (version 0.12+).

To set up an isolated development environment with desktop and CI dependencies:

```bash
uv sync --locked --extra desktop --group desktop-build --group ci --no-default-groups
```

---

## 3. Testing

All test suites use Python's built-in `unittest` framework:

### Desktop Tests
Run all desktop unit and UI tests:

```bash
uv run --no-sync python -m unittest discover -s tests -p "test_desktop*.py" -v
```

### Full Reference Verification
Run the complete reference and formal verification sequence (18 sequential checks):

```bash
uv run --no-sync python scripts/verify_all.py
```

---

## 4. Code Quality and Linting

CETA enforces standard Python lint gates via Ruff:

```bash
uv run --no-sync ruff check --select F,E9 src scripts tests examples
```

### Network Import Boundary Gate
The desktop application strictly confines external network imports to designated transport modules (`models.py` and `updates.py`). Verify that no other modules import network clients:

```bash
uv run --no-sync python scripts/network_boundary.py
```

---

## 5. Package Integrity & Manifest Verification

All files in the package payload are tracked in `PACKAGE_MANIFEST.json` and checksummed in `SHA256SUMS`.
Any modification, addition, or removal of tracked files requires regenerating the manifest and checksums:

```bash
# Regenerate manifest and checksums
python scripts/build_package_manifest.py
python scripts/build_sha256sums.py

# Verify package integrity
python scripts/verify_package.py
```

`verify_package.py` must report `PACKAGE VERIFY: PASS` on a clean working tree before committing.
