# Flylingual

## Project overview

Flylingual is an AI-native Unity action game where the player guides a fruit fly with natural-language instructions while trying to avoid falling, getting stuck, and being hit by a fly swatter. Player intent is converted into a small, bounded set of neural stimulation commands, processed by a project-specific experimental leaky integrate-and-fire (LIF) simulation built on the public MaleCNS connectome, decoded into motor output, and used to drive a six-legged physical fly in Unity. Environmental events can also feed back into the neural simulation, and measured neural responses can be returned to the conversational layer so the fly can comment on what was actually observed.

## Challenge track

**Track 1: AI-Native Game Prototype**

Flylingual treats AI as part of the game loop rather than as a content-generation add-on: language is the player's control interface, neural simulation mediates movement, and AI-driven conversation reflects measured game and neural state back to the player.

## How we used OpenAI technology

- **OpenAI GPT-Live** is used in the Dev/Demo conversational runtime as the fly's real-time voice and dialogue layer. It receives player speech, participates in intent interpretation, and turns validated game/neural observations into short in-character responses.
- **Measured neural feedback is grounded before it reaches GPT-Live.** The Bridge sends bounded observations such as selected neural readouts and experimentally observed threat-response activity; GPT-Live is instructed to preserve uncertainty and not invent emotions, causality, or biological conclusions that were not measured.
- **Player language does not directly set Unity motor values.** Movement requests are constrained to the existing action vocabulary and pass through the Brain simulation, neural readout, motor decoder, and Unity body-control path.
- **OpenAI Codex and ChatGPT** were used throughout development for implementation, debugging, code review, scientific-boundary checks, test design, documentation, and submission preparation.
- The shareable **Judge build does not embed an OpenAI API key**. The default package supports GPT-Live voice through a Vercel-authenticated WebRTC session; the OpenAI key stays on the server. A limited review access pass is bundled, with new session access available through September 18, 2026 (Japan time). A text-only edition requires the explicit `--text-only` packaging option. See [packaging instructions](Docs/windows/Package-Submission.md).

## Getting started and how to play

### Requirements

The submitted Judge build is a **Windows 64-bit voice build**. It has been tested on Windows 11.

You need:

- a Windows PC,
- a microphone,
- headphones or speakers (headphones are recommended), and
- an internet connection for GPT-Live voice conversation and free-form language interpretation.

Python, the experimental Brain runtime, and the required voice libraries are bundled with the submission. You do **not** need to install Python or enter an OpenAI API key.

### Launching the game

1. **Extract the entire submitted ZIP file.** Do not run the executable directly from inside the ZIP.
2. Open the extracted `Flylingual-Judge` folder.
3. Launch **`FlylingualConversation.exe`**.
4. The title screen may initially show that connections are being prepared. The bundled Brain and Bridge start automatically, and the initial Brain preparation can take some time.
5. Wait until **Start** becomes available, then start the game.
6. The current game interface and fly replies use English.
7. Read the first-run instructions before moving the fly.

If Windows asks for microphone permission, allow microphone access so the voice-control mode can receive your instructions.

### Objective

Guide the fly safely through the course and reach the goal.

The main hazards are:

- **falling off the course,**
- **getting stuck or failing to make progress,** and
- **the fly swatter.**

The swatter timer begins after gameplay starts. If the fly remains inactive for too long, a warning appears and the swatter approaches. Move the fly far enough before impact to escape.

### Controlling the fly

Speak naturally to the fly. Simple instructions are the most reliable starting point, for example:

- **“Move forward.”**
- **“Turn right.”**
- **“Turn left.”**
- **“Stop.”**

You can also use broader natural-language instructions. The system interprets the request, constrains it to the game's supported action vocabulary, sends the corresponding stimulation through the experimental neural simulation, decodes the resulting motor output, and applies that output to the physical fly in Unity.

In other words, language does not directly teleport or directly set the fly's velocity: the intended control path is:

```text
Player speech
  -> language / intent interpretation
  -> bounded neural stimulation
  -> MaleCNS-based experimental LIF simulation
  -> neural motor readout
  -> motor decoder
  -> six-legged Unity physics body
```

During play, the fly may also comment on measured game or neural observations. These comments are intentionally limited to what the system actually observed; they are not claims that subjective fly emotions have been measured.

### Failure, retry, and goal

- If the fly **falls** or is **hit by the swatter**, the run ends with **Game Over**.
- Choose **Retry** to return to the starting point and begin a new attempt. The game re-establishes the stopped control state before resuming movement.
- Reach the **goal area** to complete the course.

The submission scene includes an expanded finish boundary and bounded game-side steering assistance to make completion practical during judging. These assists are gameplay mechanics; they are **not** neural learning, measured neural responses, or evidence that the Brain model learned the course.

### If voice control is not responding

- Confirm that the title screen finished preparing the connection before starting.
- Check that Windows microphone access is enabled for the application.
- Check your internet connection.
- Try a short command such as **“forward”**, **“right”**, **“left”**, or **“stop.”**
- If a run ends, use the in-game **Retry** flow rather than relaunching during an active attempt.

Closing the game also shuts down the local Bridge and Brain processes that the application started.

> **Review-access note:** the submitted voice build uses a scoped review-access credential rather than an OpenAI API key. New voice-session access is configured to remain available through **September 18, 2026 (Japan time)**. The review-access package should not be publicly redistributed.

A separately packaged text-only edition can be created for environments where voice access is unavailable; that edition accepts typed instructions instead of GPT-Live microphone control.

Current Windows handoff and build notes: [README_WINDOWS.md](README_WINDOWS.md).

The current game interface and fly replies are English-only. Wait on the title screen while connections are prepared, then start the game. Questions can be answered while the fly keeps walking. If a movement request is unclear, the fly asks for clarification instead of substituting a direction from course guidance. The fly speaks in everyday language, with any apparent feelings treated as character expressions. See [implementation and validation limits](Docs/windows/English-Only-Route-Guidance.md).

The submission scene also enables optional [Unity-side goal assistance](Docs/windows/Demo-Safety-Assist.md): a wider finish boundary and bounded steering corrections during active forward requests. This is gameplay assistance, not a measured neural response, sensory-input model, or evidence of learning.

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

The voice edition additionally bundles **aiortc 1.14.0** and its media/cryptography dependencies, including **PyAV 16.1.0**. Their distribution metadata and license notices are included in the portable Python environment.

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
