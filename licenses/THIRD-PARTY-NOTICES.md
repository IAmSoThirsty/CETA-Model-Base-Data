# CETA third-party software

CETA uses Qt, PySide6, and Shiboken 6.11.2 under the GNU Lesser General
Public License version 3. These libraries are dynamically linked and unmodified.
Their LGPLv3 and GPLv3 license texts, copyright notices, and bundled third-party
attributions are included in the `Qt` folder beside this notice. Notices for
Python, cryptography, cffi, pycparser, PyInstaller, and NSIS are also included.
Each component's `INDEX.json` maps the shorter notice filenames to their original
source paths. License text is retained without modification.

The Qt modules distributed with this application are Core, Gui, Network, Widgets,
and Svg. Source-project notices also describe optional components that are not
included in this application. This notice does not restrict any rights granted
by the dependencies' licenses.

## Corresponding library source

The release includes `CETA-0.3.0-dependency-sources.zip` alongside its installer.
It contains the complete Qt Base, Qt SVG, and PySide/Shiboken source archives for
6.11.2, including their build files. `desktop-sources.json` records the upstream
locations and verified SHA-256 checksums. The publisher must distribute this
source companion with every downloadable installer and keep both available at
the same release location. A local candidate does not establish public availability.

## Using modified libraries

You may modify these LGPL libraries, replace them with compatible builds, and
debug modifications, including reverse engineering for that purpose. Close
CETA first. Keep a backup of the installation folder. Build the library with
a compatible Windows x64 toolchain, Python stable ABI, and Qt interface using the
instructions in the corresponding source archive. Replace the matching shared
`.dll` and `.pyd` files under the installation's `_internal` folder, retaining
the same relative layout, then start `CETA.exe` normally. The application
does not verify or enforce hashes or signatures for these shared libraries.
Keep your original installation backup if your modified build is incompatible.
Application updates can replace library files, so retain your modified builds
separately if you wish to apply them again after an update.

The verified downloaded installer is checked as a release artifact before it is
saved. This check does not restrict running compatible modified local libraries.
Conversations and model packs are in a separate application-data folder.

See [Qt's upstream explanation](https://www.qt.io/development/open-source-lgpl-obligations).

## Optional managed Ollama runtime

CETA's managed runtime controls download or import the official standalone Ollama
0.34.3 Windows x64 distribution only when explicitly requested. Runtime binaries
and models are not bundled with the CETA installer. The catalog in
`ceta_desktop/runtime_catalog.json` retains the upstream Ollama MIT license text
and pins every file in that optional archive. The Models page's **Runtime licenses**
control shows that license and the dependency-notice paths before downloading.

The imported runtime's `lib/ollama` directory retains all license, copyright and
notice files supplied in the archive, without modification. Those dependencies
carry their own terms. CETA verifies this managed distribution against its pinned
catalog; the advanced existing-runtime path remains available for other or
modified compatible installations. These managed runtime checks do not change
the Qt library replacement rights and instructions above.

Upstream: [Ollama v0.34.3](https://github.com/ollama/ollama/releases/tag/v0.34.3)
and [its MIT license](https://raw.githubusercontent.com/ollama/ollama/v0.34.3/LICENSE).

## Optional managed Qwen3 models

The managed model catalog offers optional Qwen3 text models from the Ollama
registry. Model weights are not bundled with CETA and are acquired only through
an explicit download or offline import. `ceta_desktop/model_catalog.json` pins
each model manifest and all referenced files, including the upstream Apache 2.0
license text. **Model license** displays that text before acquisition.

Verified installation preserves the upstream license blob without modification;
CETA's offline model export includes it with the original manifest and all other
referenced blobs. Import verifies the same pinned files. Model assets carry their
own license terms; their inclusion in the catalog is not a claim about model
quality or compatibility with every computer.
