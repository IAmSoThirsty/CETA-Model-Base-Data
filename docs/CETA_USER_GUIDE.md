# CETA

CETA is the official application name. New installations use the CETA application
data folder. If the earlier pre-release name, ThirstyAI, already has a conversation
database and no CETA folder exists, CETA continues using that database in place.
It does not move or merge data folders. If both folders exist, CETA uses its own
folder; an earlier database can be selected explicitly with `--data-dir`.

CETA is a native Windows desktop environment for working with local files,
conversations, and commands. Models are optional expansion packs.

## Working with files

Choose **Open workspace** and select a folder. Double-click a UTF-8 text file to
edit it. **Save file** or **Ctrl+S** saves explicitly. If another program changed
the file, CETA refuses to replace that change. Reopen the file and reconcile
your edits. Existing UTF-8 byte-order marks and consistent line endings survive
saves. Binary files, mixed line endings, and files above 4 MiB are not editable.
Unsaved editor drafts are periodically retained in local application data and
reopened after a crash. Recovered drafts do not replace disk files automatically.

Use **File > New file** to create a file inside the workspace and **Ctrl+F** to
find text in the current file. Native undo/redo, selection, and clipboard actions
are available in the editor.

## Conversations

In **Model packs**, connect to an OpenAI-compatible local model service, choose a
model, and return to **Workbench**. Enter a message and click **Send**. **Stop**
cancels generation. Incomplete or failed responses are identified in history.
Unsent messages are saved with their conversation. Responses are checkpointed
while they stream; after an interruption, the saved portion is marked interrupted.
Model loading can take up to two minutes without output before the request times
out. Stop remains available while waiting.

**Add open file to message** includes the editor's current contents in your draft.
Review the draft before sending. Workspace files are never attached automatically.
Assistant text cannot itself run commands or save files.

**Conversations** lists saved discussions. Double-click one to continue it.
Export creates a new JSON file without overwriting an existing export.

## Model expansion packs

Two local model paths are supported:

- **Ollama:** install the local runtime from [Ollama](https://ollama.com), then use
  **Start installed Ollama service**. Enter a model name supported by that runtime
  and choose **Download pack**. This explicitly requests a download through Ollama;
  model sizes, licenses, and hardware requirements depend on the chosen model.
  Connect/refresh when installation finishes.
- **GGUF:** choose **Install GGUF pack** to copy and checksum a local GGUF file.
  Select the installed pack, choose **Start selected pack**, and select your
  trusted `llama-server` executable from [llama.cpp](https://github.com/ggml-org/llama.cpp).
  Connect/refresh after the model finishes loading.

Import validation establishes format header, size, and byte identity; it does not
establish model quality or license rights. Model packs do not contain executable
extensions. No model is included in the desktop installer.

CETA starts Ollama with cloud features disabled for that process. Model-file
downloads still require an internet connection. This setting does not change an
Ollama service that was already running or any service you start separately.
Before connecting to another service, check its privacy settings: a local address
does not guarantee local inference, and that service may forward your messages
and attached file contents to a cloud provider. See Ollama's
[local-only configuration](https://docs.ollama.com/faq#how-do-i-disable-ollamas-cloud-features).

## Workloads

Open a workspace, type a command, and click **Run**. Windows commands execute in a
PowerShell process under your account, with that workspace as the current folder.
The output panel shows results; **Stop** terminates the application's process tree.
Commands have your account's normal permissions and are not an operating-system
sandbox. Conversation text is not an execution request.
The **Workloads** page shows the last 100 recorded commands and their saved output.

## Updates and data

Application updates are separate from model packs. A configured publisher channel
must supply a valid signed manifest; the downloaded installer must match its signed
size and checksum. After downloading, choose **Install update and close CETA**
and confirm. Stop active conversations, downloads, and workloads first. Unsaved
files still receive the normal Save/Discard/Cancel prompt; Cancel keeps CETA open.
CETA saves conversation drafts, closes its model service, and releases its data
locks before starting the installer. The installer waits for CETA to finish exiting.
The saved file is checked again against its signed size and checksum at launch;
a changed or missing file is not executed. If launch fails, reopen CETA and
download the update again. You can also close CETA and run the downloaded installer
yourself. Downloading alone never starts installation.
Download progress is shown, and **Cancel update download** stops the download
without publishing a partial installer. Network cancellation can take up to the
current connection's 15-second read timeout.

The release channel is hosted at
`https://www.thirstysystems.com/ceta/updates/stable.json`. It accepts only manifests
signed with CETA's dedicated personal Ed25519 publisher key. Until the first
manifest is published, a channel check may report that it is unavailable.

## Personally verified downloads

The publisher provides a separate CETA verification package with the public key,
its fingerprint, a signed installer receipt, and verification instructions.
Receive the key fingerprint directly from the publisher through a channel you
already trust. Check that fingerprint and the receipt before running an installer.
A public key delivered only beside a download is not independent identity proof.

This personal signature is not a Windows certificate-authority signature.
Windows may report an unrecognized publisher. The verification package does not
install root certificates or change Windows trust settings. Never share a private
signing key; recipients need only the public key and signed receipt.

Conversations, settings, and GGUF packs live in the application data folder shown
under **Updates & about**. Ollama manages its own model storage. Close CETA
before backing up its entire application data folder. Restore that folder with the
application closed and use the same or a newer compatible application version.
Uninstall removes installed application files; it preserves application data and
unrecognized files in the installation directory.

**Updates & about** also identifies the Qt libraries and opens the included
dependency notices. The release's dependency-source companion contains their
matching source archives and instructions for using compatible modified libraries.
