# CETA

CETA is the official application name. New installations use the CETA application
data folder. If the earlier pre-release name, ThirstyAI, already has a conversation
database and no CETA folder exists, CETA continues using that database in place.
It does not move or merge data folders. If both folders exist, CETA uses its own
folder; an earlier database can be selected explicitly with `--data-dir`.

CETA is a native Windows desktop environment for working with local files,
conversations, and commands. Models are optional expansion packs.

## Find your way around

Use the left sidebar to switch between seven sections. Each has its own planetary
landscape; changing sections does not download a model or start a workload.

| Section | What you can do |
| --- | --- |
| **Chat** | Start or resume a conversation, choose a connected local model, and send a message. |
| **Projects** | Open a workspace folder, edit files, and run explicit commands in its terminal. |
| **Library** | Find saved conversations, continue them, or export the selected conversation. |
| **Models** | Connect to a local runtime, download optional Ollama packs, or import GGUF files. |
| **Workloads** | Review recorded commands, their status, and saved output. |
| **Updates** | Check the signed update channel, download and install an update, or read dependency notices. |
| **Settings** | Change editor font size and wrapping, locate local application data, and review shortcuts. |

You can browse and edit a workspace before installing any model. Chat requires
a running local model service and an available model; a decorative planet or a
model-name example is not evidence that a model is installed.

## Project tasks and evidence

CETA 0.4.0 integrates the selected Model 001 context, claims, decisions and role
components into the existing CETA application. Open a workspace in **Projects**,
open **Task and evidence**, enter an objective and start a task. **Inspect project**,
**Search**, **Current context** and
**Timeline** operate within that project and task. Inspection reports the current
Git state when available, applicable instructions, file revisions and omitted
paths. Sensitive filenames, Git internals, nested repositories and filesystem
aliases are excluded or refused; the results explicitly identify omissions and
context limits. Inspection and manual editing work without a model.

Choose an existing task to resume its history. Project changes invalidate compiled
context before dependent edits or commands. Open a file, edit it, choose **Review
editor diff**, then **Apply reviewed edit**. A changed file or editor draft requires a
new review. **Save file** uses the same authority and evidence path and preserves
the existing conflict checks. Multi-file atomic application is not supported;
each file receives a separate reviewed action and observed outcome.

New conversations belong to their current task. Existing unassigned conversations
can be explicitly attached to a task; their prior text is marked historical and
does not become fresh evidence. Project/task selection controls subsequent chat
context. The chat composer's **Response role** selector offers **Assistant**,
**Reviewer** and **Specialist** using the same selected local provider and task grant. Their output is an unverified proposal, not user authority
or independent corroboration. Model output cannot execute commands or grant itself
permission to edit.

Commands run only after the user requests the exact command. This is **trusted
local execution** with the user's ordinary operating-system access. CETA records
the executable, arguments, working directory, timeout, output and exit status.
Windows job ownership supports cancellation and cleanup of owned child processes.
It does not provide filesystem or network sandboxing. A successful exit is not
independent proof that all effects of a command were correct.

**Timeline** contains the task's captures, context receipts, decisions, consumed
permits, observed effects and actual outcomes. Verified file edits are independently
read back and compared with the reviewed bytes. An interrupted or uncertain effect
is labelled **needs_reconciliation**; CETA does not replay its consumed proposal.
Inspect actual files/output and create a new explicitly reviewed operation if
further work is needed. Provider interruptions retain their recorded partial text.

Use **Import historical log…** in **Task and evidence** to select an old CETA
journal for the current project. Choose its kind, enter the project scope statement,
and confirm the exact source file, SHA-256 and project in the review dialog. Import preserves original bytes and record order; it does not activate
old permits or certify historical assertions as true. No other project's history
is discovered or imported automatically.

## Local history and upgrades

CETA 0.4.0 uses desktop database schema 2. Before a schema-1 migration it creates
and verifies a uniquely named backup beside the database; originals and unknown
records are retained. Existing legacy transcripts remain unassigned until selected.
New project operations share one hash-chained event stream per project. Conversation,
workload and task views are checked against that history. The application stream
records settings and model/update/export operations without assigning them to an
unrelated coding project.

Runtime signing keys are generated locally and protected with Windows current-user
DPAPI. They are separate from publisher release keys. This is a trusted single-user
desktop boundary; it does not prove tamper resistance against that user or establish
an external rollback anchor. Missing/corrupt history or a future schema produces an
error. After schema-2 events exist, recover forward and retain them; do not replace
the database with an old backup or run an older schema-1 binary on it.

## Projects: working with files

In **Projects**, choose **Open workspace** and select a folder. Double-click a UTF-8 text file to
edit it. **Save file** or **Ctrl+S** saves explicitly. If another program changed
the file, CETA refuses to replace that change. Reopen the file and reconcile
your edits. Existing UTF-8 byte-order marks and consistent line endings survive
saves. Binary files, mixed line endings, and files above 4 MiB are not editable.
Unsaved editor drafts are periodically retained in local application data and
reopened after a crash. Recovered drafts do not replace disk files automatically.
If the original folder or file is temporarily unavailable, closing CETA retains
the recovery draft so it can reopen when the file becomes available again.

Use **New file** or **File > New file** to create a file inside the workspace and **Ctrl+F** to
find text in the current file. Native undo/redo, selection, and clipboard actions
are available in the editor.

## Chat: conversations

In **Models**, connect to an OpenAI-compatible local model service with
**Connect / refresh models**, choose an available model, and return to **Chat**.
The model selectors in Models, the Chat header, and the message composer stay in
sync. Choose **New Chat** or press **Ctrl+N**, enter a message, and click **Send**. **Stop**
cancels generation. Incomplete or failed responses are identified in history.
Unsent messages are saved with their conversation. Responses are checkpointed
while they stream; after an interruption, the saved portion is marked interrupted.
Model loading can take up to two minutes without output before the request times
out. Stop remains available while waiting.

The composer's **Open file** button adds the file already open in the Projects
editor to your message draft. It does not open a file picker or attach a whole
workspace. Use **Workspace** to switch to Projects first if you need to open a
file. Review the resulting draft before sending. CETA sends the active task objective,
project inventory and applicable instructions as context; explicitly selected file
content is included when requested. Inspect **Current context** before generation to review
the captured scope. Assistant text cannot itself run commands or save files.

Click a saved discussion in Chat's **Conversations** list to resume it. **Search
conversations** filters the displayed titles and dates, not the entire message
contents. Stop an active response before switching conversations. Fenced code
blocks have a **Copy code** action that copies their contents to the clipboard;
it does not execute or save the code.

Use **Export conversation…** or **Ctrl+Shift+E** to export the current conversation.
Exports create a new JSON file and refuse to overwrite an existing file.

Unassigned legacy conversations retain **Delete conversation**, which removes the
selected local transcript and draft after confirmation. Once assigned to a task,
the action is **Archive conversation**: it hides the conversation and clears its
draft while retaining its messages and evidence in project history. Archive does
not erase data. CETA does not silently assign old conversations to a project.

## Library: saved conversations

The **Library** lists the same locally saved discussions. Use **Find a saved
conversation** to filter its displayed titles and dates. Select an item and choose
**Continue conversation**, or double-click it, to return to Chat. **Export selected…**
exports that selected discussion without changing which conversation is open in
Chat. **Open project files** takes you to Projects.

## Model expansion packs

Opening **Models** checks physical RAM, available RAM, logical CPU count, and
detected graphics hardware locally. **Recheck hardware** refreshes that snapshot.
These readings belong to the computer where the app is running. No developer
machine profile is bundled or stored as another user's settings.
The model selector shows explicit quantized candidates, approximate download sizes,
and whether their estimated memory needs fit GPU memory or available system RAM.
Unmeasured graphics memory is not counted as usable VRAM. CPU fallback can be slow.
Windows GPU names and dedicated memory are read through native DXGI; available
process budgets are explicitly labelled because the model service's budget may
differ. NVIDIA free VRAM comes from `nvidia-smi` when available. Unavailable APIs
leave unknown values. Shared RAM and multiple GPU memories are not added together
as if they were one dedicated GPU.

**Use suggested model** fills the download name; it does not download or start a
model. CETA leaves manually entered names unchanged when checking hardware. Known
catalog models are checked again before download, and imported GGUF packs before
starting. If measured free memory is insufficient, close other applications or
choose a smaller model. Custom model tags remain available with unassessed memory
requirements. These estimates assume one request, one loaded model, and a
4,096-token context; they do not guarantee loading, speed, or response quality.

The catalog's approximate download sizes come from the official
[Qwen3 tags](https://ollama.com/library/qwen3/tags) and
[gpt-oss tags](https://ollama.com/library/gpt-oss/tags). Working-memory estimates
are CETA policy, not publisher measurements. See Ollama's
[context memory guidance](https://docs.ollama.com/context-length) and
[hardware support](https://docs.ollama.com/gpu) for runtime requirements.

Two local model paths are supported:

- **Ollama:** install the local runtime from [Ollama](https://ollama.com), then use
  **Start installed Ollama** in Models. Enter a model name supported by that runtime
  and choose **Download pack**. This explicitly requests a download through Ollama;
  model sizes, licenses, and hardware requirements depend on the chosen model.
  Connect/refresh when installation finishes.
- **GGUF:** choose **Import GGUF pack…** to copy and checksum a local GGUF file.
  Select the installed pack, choose **Start selected pack…**, and select your
  trusted `llama-server` executable from [llama.cpp](https://github.com/ggml-org/llama.cpp).
  Connect/refresh after the model finishes loading.

Import validation establishes format header, size, and byte identity; it does not
establish model quality or license rights. Model packs do not contain executable
extensions. No model is included in the desktop installer.

CETA starts Ollama with cloud features disabled for that process. Model-file
downloads still require an internet connection. This setting does not change an
Ollama service that was already running or any service you start separately.
CETA-started Ollama limits loaded models and parallel requests to one and sets a
4,096-token context. Ordinary Ollama chat requests also use that context limit.
Before connecting to another service, check its privacy settings: a local address
does not guarantee local inference, and that service may forward your messages
and attached file contents to a cloud provider. See Ollama's
[local-only configuration](https://docs.ollama.com/faq#how-do-i-disable-ollamas-cloud-features).

After connecting, choose **Test selected local model** to request one short response
from a model the Ollama service reports as local. The result shows actual response
time and any runtime-reported VRAM allocation separately from hardware estimates.
This check cannot certify the service's implementation or establish general model
quality. Merely discovering a model does not verify that it can generate a response.
Known cloud-backed model aliases are excluded from the local model list.
They are also rejected before conversation text is sent. Other OpenAI-compatible
services remain explicitly unverified for inference locality. The test uses a
synthetic prompt, does not send saved conversations, and applies only to the
selected model and endpoint at that time.

CETA provides text conversations and code assistance using separately installed
local models. It does not install the hosted ChatGPT service. Additional memory
does not automatically add web access, vision, voice, or autonomous execution.
Downloading weights and application updates requires connectivity; installed
local weights can generate responses without an internet connection.

## Projects terminal and Workloads

In **Projects**, open a workspace, type a command in **Terminal**, and click **Run**.
Windows commands execute in a
PowerShell process under your account, with that workspace as the current folder.
The output panel shows results; **Stop** terminates the application's process tree.
Commands have your account's normal permissions and are not an operating-system
sandbox. Conversation text is not an execution request.
The **Workloads** page shows the last 100 recorded commands and their saved output.
Select a history entry to inspect its output. **Go to project terminal** returns
to Projects to start another command. The terminal displays command output; it
does not provide an interactive shell input session.

## Settings

Under **Editor preferences**, choose a **Code font size** from 10 to 22 points and
optionally enable **Wrap long lines in the editor**. These preferences apply
immediately and are saved locally for the next launch. Visual wrapping does not
insert line breaks into a file.

**Local data & privacy** shows CETA's application data path. **Open data folder**
opens that directory in Windows. Local storage uses your Windows account's file
permissions; export conversations only when you intend to share their contents.
Model services started separately retain their own privacy settings.

| Shortcut | Action |
| --- | --- |
| **Ctrl+N** | New chat |
| **Ctrl+O** | Open workspace |
| **Ctrl+S** | Save the open file |
| **Ctrl+F** | Find in the open file |
| **Ctrl+Shift+N** | New file |
| **Ctrl+Shift+E** | Export the current chat |

## Updates and data

In **Updates**, choose **Check for updates**. Application updates are separate from
model packs. A configured publisher channel
must supply a valid signed manifest; the downloaded installer must match its signed
size and checksum. Choose **Download verified update…** when an update is available.
After downloading, choose **Install update and close CETA…**
and confirm. Stop active conversations, downloads, and workloads first. Unsaved
files still receive the normal Save/Discard/Cancel prompt; Cancel keeps CETA open.
CETA saves conversation drafts, closes its model service, and releases its data
locks before starting the installer. The installer waits for CETA to finish exiting.
The saved file is checked again against its signed size and checksum at launch;
a changed or missing file is not executed. If launch fails, reopen CETA and
download the update again. You can also close CETA and run the downloaded installer
yourself. Downloading alone never starts installation.
Download progress is shown, and **Cancel download** on the Updates page stops the download
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
under **Settings > Local data & privacy**. Ollama manages its own model storage. Close CETA
before backing up its entire application data folder. Restore that folder with the
application closed and use the same or a newer compatible application version.
Uninstall removes installed application files; it preserves application data and
unrecognized files in the installation directory.

**Updates** also identifies the Qt libraries and opens the included
dependency notices. The release's dependency-source companion contains their
matching source archives and instructions for using compatible modified libraries.
