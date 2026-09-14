# Flylingual

Flylingual is a Unity prototype in which player language is translated into bounded neural stimulation, processed through a project-specific experimental LIF simulation built on the public MaleCNS connectome, decoded into movement, and returned to the player through game/environment observations and conversational feedback.

Current Windows handoff and build notes: [README_WINDOWS.md](README_WINDOWS.md).

> **Scientific scope:** MaleCNS is a connectome dataset, not a finished brain emulator. The neural dynamics, stimulation policy, motor decoder, threat-event proxy, Unity body, and dialogue integration in this repository are project-specific experimental work. `ready=false` is intentionally retained where validation is incomplete.

## Pre-existing and third-party asset disclosure

This section documents the material pre-existing code, open-source software, datasets, third-party packages, authoring tools, and hosted services used by or included with the submitted project. It is intended for submission disclosure and attribution. It does **not** replace upstream license texts or service terms; the original license/terms of each component control.

### First-party project code and assets

Unless explicitly listed below as third-party/pre-existing material, the Unity gameplay and physical fly implementation, Bridge/control code, MaleCNS adaptation, neural readout/feedback code, environment/game logic, HUD, Vercel API wrapper, and submission tooling are project-specific code in this repository. No top-level open-source license for this first-party project code is declared at the time of submission.

The fly visual asset (`ArtSource/Blender/FlyVisual.blend` and the Unity FBX export) was procedurally authored for this project from `ArtSource/Blender/generate_fly.py`. No external mesh, image, texture, scientific reconstruction, paid asset, or downloaded generative asset was used for that model. See [ArtSource/Blender/README.md](ArtSource/Blender/README.md).

### Pre-existing research code / reference implementation

| Component | How it is used | License | Source / notice |
|---|---|---|---|
| Philip Shiu / Nico Spiller **Drosophila_brain_model** | A frozen reference/baseline snapshot is kept under `Brain/ShiuBaseline/`. The current MaleCNS runtime is project-specific and is described as *Shiu-compatible* rather than an official upstream runtime. | **MIT** | Upstream: https://github.com/philshiu/Drosophila_brain_model — bundled license: [`Brain/ShiuBaseline/LICENSE`](Brain/ShiuBaseline/LICENSE) |

The upstream repository accompanies the Drosophila computational brain-model work. Retaining this attribution does not imply that the MaleCNS dataset authors or the Shiu-model authors validate or endorse Flylingual's custom dynamics or game behavior.

### Dataset and derived connectome data

| Component | How it is used | License | Source / attribution |
|---|---|---|---|
| **MaleCNS v1.0** Drosophila male central nervous system connectome | Source for neuron annotations/connectivity and the derived runtime graph/readout mappings used by the experimental MaleCNS backend. Raw Feather source files are kept outside Git; submission/runtime artifacts may contain transformed arrays/atlas data derived from the dataset. | **CC BY 4.0** | https://male-cns.janelia.org/ and https://male-cns.janelia.org/download/ |

**MaleCNS attribution:** Derived from the male CNS connectome, neuPrint dataset `male-cns:v1.0`, produced by the FlyEM Project Team (HHMI Janelia Research Campus), the Drosophila Connectomics Group (University of Cambridge / MRC Laboratory of Molecular Biology), and Google Research; licensed under Creative Commons Attribution 4.0 International (CC BY 4.0).

Publication: Berg S, Beckett IR, Costa M, Schlegel P, Januszewski M, et al., *Sexual dimorphism in the complete Drosophila male central nervous system connectome*, Cell 189(18):5504-5526.e15 (2026), https://doi.org/10.1016/j.cell.2026.08.015.

**Project modifications:** MaleCNS source data is transformed into project-specific graph/CSR arrays and selected readout/stimulation mappings. Flylingual applies its own experimental neurotransmitter/sign assumptions, LIF dynamics, weighting/scaling choices, stimulation policies, temporal motor decoder, visual-threat event proxy, and Unity body controller. Those transformations are not measurements or validated dynamics supplied by the MaleCNS creators. No affiliation or endorsement by HHMI/Janelia, the University of Cambridge, MRC LMB, Google Research, or the MaleCNS authors is implied.

### Unity engine and Unity packages

The project is built with **Unity 6000.5.9f1**. Unity Engine/runtime use and redistribution are governed by the applicable [Unity Terms of Service](https://unity.com/legal/terms-of-service) and related Unity terms.

Direct Unity package dependencies recorded in `UnityProject/Packages/manifest.json` include:

| Component | Version | License / terms |
|---|---:|---|
| Unity Input System (`com.unity.inputsystem`) | 1.20.0 | **Unity Companion License** for Unity-dependent projects, plus any package third-party notices |
| Universal Render Pipeline (`com.unity.render-pipelines.universal`) | 17.5.0 | **Unity Companion License** for Unity-dependent projects, plus any package third-party notices |
| Unity Pipeline (`com.unity.pipeline`) | 0.7.0-exp.1 | Unity package; governed by the package-specific license shipped by Unity and applicable Unity terms. Used for Editor/CLI development workflow, not as an independently licensed project asset. |
| Unity built-in modules (Physics, UIElements, Audio, etc.) | 1.0.0 modules | Unity software/package terms |

Resolved Unity packages also include Burst, Collections, Mathematics, Shader Graph, Mono.Cecil, Newtonsoft.Json, NUnit/test packages, and other transitive dependencies. Their package-specific `LICENSE` / `Third Party Notices` files and Unity package notices control. See `UnityProject/Packages/packages-lock.json` for the resolved versions.

### Bundled Judge Python runtime

The portable Judge package is prepared from **CPython 3.11.9** and installs the following major direct runtime dependencies. Package-specific transitive dependencies are also distributed with their own metadata/license files in the portable Python environment.

| Component | Version | License |
|---|---:|---|
| CPython | 3.11.9 | **PSF License Agreement** (plus incorporated-software notices) |
| NumPy | 1.24.3 | **BSD-3-Clause** |
| Numba | 0.61.2 | **BSD-2-Clause** |
| llvmlite | 0.44.0 | **BSD-2-Clause** |
| psutil | 7.2.2 | **BSD-3-Clause** |
| aiohttp | 3.14.3 | **Apache-2.0** |

The exact portable-runtime versions are pinned by `tools/prepare_judge_python.ps1`, which also records an installation manifest for the produced distribution.

### Research / rebuild dependencies not required by the packaged Judge runtime

The repository also contains data-rebuild and research workflows whose pinned Windows environment includes the following material dependencies:

| Component | Version in repository environment | License |
|---|---:|---|
| Brian2 | 2.5.1 | **CeCILL 2.1** |
| Cython | 0.29.37 | **Apache-2.0** |
| NumPy | 1.24.3 | **BSD-3-Clause** |
| pandas | 2.3.3 | **BSD-3-Clause** |
| PyArrow / Apache Arrow | 24.0.0 | **Apache-2.0** (with upstream third-party notices) |
| psutil | 7.2.2 | **BSD-3-Clause** |

These tools are used to inspect/rebuild research data or historical baselines; the current Judge runtime uses the bundled Numba/llvmlite MaleCNS path rather than Brian2.

### Vercel backend source dependencies

`backend/hayeringual-api` is a project-specific wrapper deployed to Vercel. Its important direct dependencies are:

| Component | Version | License |
|---|---:|---|
| Vercel AI SDK (`ai`) | 7.0.99 | **Apache-2.0** |
| `@ai-sdk/gateway` | 4.0.80 | **Apache-2.0** |
| Next.js | 16.3.5 | **MIT** |
| React / React DOM | 19.3.0 | **MIT** |
| Zod | 4.6.5 | **MIT** |
| TypeScript (development) | 7.0.2 | **Apache-2.0** |

See `backend/hayeringual-api/package.json` and `package-lock.json` for the complete dependency tree and exact resolved metadata.

### Authoring and development tools

| Tool | Use in this project | License / terms | Runtime requirement? |
|---|---|---|---|
| Blender 4.2.2 LTS | Local procedural authoring/export of the original fly visual | **GNU GPL v2 or later** for Blender itself; Blender's license does not claim ownership of artwork created with Blender | No |
| `ahujasid/blender-mcp` | Optional local Blender authoring/MCP helper; telemetry was disabled in this repository's documented authoring setup | **MIT** | No |
| Unity Editor / Unity CLI / Unity Pipeline | Development, build, testing, Editor automation | Unity terms / applicable package terms | Editor/CLI not required by packaged Player |
| OpenAI Codex / ChatGPT | AI-assisted planning, coding, review, and debugging during development | Hosted service; governed by applicable OpenAI terms | No model weights/runtime are bundled by virtue of using the development tool |

### Hosted AI / cloud services (not redistributed as OSS or model weights)

These are network services, not open-source components bundled into the repository or Judge ZIP. Their applicable service terms govern use.

| Service | Project use | Terms |
|---|---|---|
| OpenAI GPT-Live / OpenAI API | Dev/Demo conversational voice path and some validation flows | OpenAI Service Terms / Services Agreement: https://openai.com/policies/service-terms/ |
| Vercel AI Gateway / Vercel hosting | Judge cloud intent/translation backend routing and hosting | Vercel AI Product Terms / Terms: https://vercel.com/legal/ai-product-terms |
| Google Gemini API / Gemini model accessed through AI Gateway | Judge cloud intent/translation model provider | Google Gemini API Additional Terms: https://ai.google.dev/gemini-api/terms |

No OpenAI, Vercel, or Google model weights are included in this repository or the packaged Unity application. API credentials are not intended to be committed or embedded in the client distribution.

### License reference links

- MaleCNS download/license: https://male-cns.janelia.org/download/
- Creative Commons Attribution 4.0: https://creativecommons.org/licenses/by/4.0/
- Shiu baseline MIT license: [`Brain/ShiuBaseline/LICENSE`](Brain/ShiuBaseline/LICENSE)
- Unity legal terms: https://unity.com/legal
- Unity Companion License information: https://unity.com/legal/licenses/unity-companion-license
- Python license: https://docs.python.org/3.11/license.html
- NumPy license: https://numpy.org/doc/stable/license.html
- Numba: https://github.com/numba/numba
- llvmlite: https://github.com/numba/llvmlite
- psutil: https://github.com/giampaolo/psutil
- aiohttp: https://github.com/aio-libs/aiohttp
- Brian2: https://github.com/brian-team/brian2
- Cython: https://cython.org/
- pandas: https://github.com/pandas-dev/pandas
- Apache Arrow / PyArrow: https://arrow.apache.org/
- Vercel AI SDK: https://github.com/vercel/ai
- Next.js: https://github.com/vercel/next.js
- React: https://github.com/facebook/react
- Zod: https://github.com/colinhacks/zod
- TypeScript: https://github.com/microsoft/TypeScript
- Blender license: https://www.blender.org/about/license/
- Blender MCP: https://github.com/ahujasid/blender-mcp

### Scope of this disclosure

This table intentionally focuses on **material direct dependencies and important pre-existing assets**. Build systems and package managers may pull additional transitive dependencies; the corresponding upstream package metadata, bundled license files, Unity `Third Party Notices`, Python distribution notices, and npm lockfile remain authoritative for those components. When a package-specific license differs from the general family described above, the package-specific license controls.
