# CETA Desktop Architecture

CETA is an offline-first, native Windows desktop workspace built with Python and PySide6 (Qt 6). It provides local text/code editing, durable local conversation storage, loopback local model integration (Ollama and GGUF), and audited workspace command execution without webviews, Electron, or cloud telemetry.

---

## 1. Module Responsibility Map

The desktop application lives in `src/ceta_desktop/`:

| Module | Responsibility |
|---|---|
| `app.py` | Central shell (`MainWindow`), navigation stack, global shortcuts, menu bar, and application entry point (`main()`). |
| `components.py` | Reusable UI builders (`button`, `action`, `page`, `card`, `filter_list`) ensuring consistent ember styling and decoupling page modules from `MainWindow`. |
| `pages/workloads.py` | Workloads page (`WorkloadsPage`): historical review of executed workspace commands, statuses, and terminal logs. |
| `pages/settings.py` | Settings page (`SettingsPage`): code font size, editor line wrapping, data folder location, and keyboard shortcuts. |
| `pages/updates.py` | Updates page (`UpdatesPage`): publisher cryptographic update checks, verified download, and installer staging. |
| `pages/library.py` | Library page (`LibraryPage`): archive browsing, search, continuing past chats, and exporting conversations. |
| `chat_widgets.py` | Native Qt chat transcript widgets (`ChatTranscript`, `_MessageRow`, `_CodePanel`), markdown prose/fence parsing, streaming display, and clipboard handling. |
| `editor.py` | Code editor gutter, syntax highlighting (`CodeHighlighter`), and editor viewport configuration (`CodeEditor`). |
| `models.py` | Loopback model client (`LocalModelClient`), socket deadline management (`ModelSocket`), local endpoint validation (`local_endpoint`), and GGUF model pack installer (`ModelPacks`). |
| `storage.py` | Durable SQLite storage (`Store`): WAL mode, synchronous=FULL, schema versioning, draft persistence, conversation records, and message history. |
| `workspace.py` | Path-confined workspace management (`Workspace`), file size bounds (max 4 MiB), UTF-8 checks, double-SHA256 collision detection, and atomic file replacement (`ReplaceFileW`). |
| `updates.py` | Cryptographic update verification (`verify_manifest`), personal Ed25519 signature checks, verified download (`download_update`), and redirect constraints. |
| `theme.py` | Dark ember palette stylesheet (`APP_STYLESHEET`), branding widgets (`BrandMark`, `EmberSidebar`, `ScenePage`), and SVG vector icon loader (`icon`). |
| `installation.py` | Safe Windows update handoff (`launch_verified_update`), verifying file lock preservation and launch arguments. |
| `instance.py` | Single-instance application mutex and marker management (`open_application_marker`, `close_application_marker`). |

---

## 2. Concurrency and Threading Model

The application utilizes native Qt primitives for all background activities to preserve responsive UI rendering:

1. **`BackgroundTask(QThread)`**:
   - Executes long-running tasks asynchronously (HTTP model streaming, remote update checking, model pack downloads).
   - Signals: `result(object)`, `failed(str)`, `token(str)`.
   - Thread cancellation is mediated via `threading.Event` polled by custom socket wrappers (`ModelSocket`).

2. **`QProcess`**:
   - Manages local runtime execution for external CLI processes:
     - Model servers (`ollama serve`, `llama-server`).
     - Workspace commands executed from the Project terminal.
   - Merges stdout/stderr channels and streams output into bounded text edit buffers.

3. **`QTimer`**:
   - Single-shot timers for debouncing draft autosave (`draft_timer`), chat draft persistence (`prompt_timer`), and chat scroll/render synchronization (`chat_render_timer`).
   - Periodic timers for saving partial assistant response progress during active generation (`response_timer`).

---

## 3. Strict Network Boundary

In accordance with offline-first and sovereignty principles:
- **`models.py`**: Restricted strictly to loopback addresses (`127.0.0.1`, `localhost`, `::1`). Any attempt to connect to external endpoints raises `ModelError`.
- **`updates.py`**: Communicates exclusively over HTTPS with the publisher's signed release channel when explicitly requested by the user.
- All other desktop modules are forbidden from importing network transport packages, enforced statically by `scripts/network_boundary.py`.

---

## 4. Storage & Persistence Architecture

Application data is rooted at `%LOCALAPPDATA%\CETA\`:
- **`desktop.sqlite3`**: SQLite database configured with:
  - `PRAGMA foreign_keys=ON`
  - `PRAGMA journal_mode=WAL`
  - `PRAGMA synchronous=FULL`
  - `PRAGMA user_version=1`
  - Tables: `settings`, `conversations`, `messages`, `workloads`.
- **Durable Drafts**: Unsaved editor changes and pending conversation prompts are stored in `settings` with SHA-256 state tracking to enable seamless recovery following unexpected application exits.
