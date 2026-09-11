# Fly Visual — original procedural sculpture

Created locally on 2026-09-11 with Blender **4.2.2 LTS**, build `c03d7d98a413`, from the checked-in `generate_fly.py` (random seed 43). No external mesh, image, texture, scientific reconstruction, generative API, download, or paid service was used. Geometry and material values were authored for this project. There are no third-party asset redistribution conditions introduced by this asset; distribution follows the project's own terms.

This is a stylized Drosophila-inspired display model, not a measured anatomical reconstruction, identified individual, or MaleCNS body reconstruction. The dark abdominal tip suggests a male appearance without claiming biological or specimen identity.

## Files and reproduction

- `FlyVisual.blend`: editable source of truth, including a presentation-only camera and three area lights.
- `generate_fly.py`: full deterministic construction and FBX export.
- `FlyVisual_preview.png`: Blender studio preview, body only.
- `../../UnityProject/Assets/FlyVisual/FlyVisual.fbx`: explicit Unity export; Blender is not required by Unity.

Run from repository root in PowerShell:

```powershell
& 'C:\Program Files\Blender Foundation\Blender 4.2\blender.exe' --background --python ArtSource/Blender/generate_fly.py
```

The script overwrites only its generated blend, preview, and FBX. It does not modify Unity scenes or physics. Blender may create a `.blend1` backup, which is not a required deliverable.

## Coordinates and integration

Authored dimensions are Unity display units, with thorax center at zero, +Z forward and +Y up. Script maps those into Blender `(x, -z, y)` then exports FBX with `axis_forward=-Z`, `axis_up=Y`, and baked space transform. Verify orientation after Unity import, rather than applying a guessed rotation.

Thorax semiaxes are `(0.62, 0.42, 0.86)`, head center `(0, .04, 1.04)`, abdomen center `(0, -.02, -1.11)`. These are presentation dimensions informed by existing `FlyLocomotionConfig.asset` thorax size `(1.4, .7, 1.8)` and root-relative leg positions. The physics root has nonuniform scale; the Unity mapper must compensate world scale rather than doubling that scale accidentally.

**This FBX contains the body only.** Six articulated legs / 18 segment pivots must be generated or attached by the Unity VisualRigMapper at the existing physical Coxa/Femur/Tibia transforms. Do not attach a static leg sculpture to the thorax. Foot placement must use actual FootPad transforms. No collider, rigidbody, articulation, force, joint, CPG, or root locomotion is contained or modified here.

Six renderer/material groups: `ChitinGold`, `AbdomenDark`, `EyeRuby`, `WingMembrane`, `WingVein`, `Bristle`. Wings have explicit geometry and veins; bands, sparse hairs, antennae and eye facets are explicit geometry. No texture baking is necessary because no procedural texture inputs are used. The Blender node rendering is not the Unity material implementation. Reconstruct materials for existing URP; wing membrane requires transparency (alpha .29) and both sides visible. The preview lighting is not exported.

## Validation and limits

Blender generation, blend save, explicit FBX export and 1280×960 Cycles render completed locally. Preview inspected visually; compound eyes now use dense contiguous flat facets (64 by 40 tessellation), replacing the previous scattered bead geometry. Body dimensions, material group names, axes, and the mapper contract are unchanged. Six-legged silhouette, actual foot contact, 18-joint tracking, Unity imported orientation/materials, four Unity camera views and walking footage remain integration checks; the Blender body render does not establish those gates. It also does not validate live brain simulation.

## Blender MCP setup (2026-09-11)

`uv` and `uvx` 0.10.7 were already available. The actual `uvx blender-mcp --help` exposes `install-addon` and `addon-paths`; `install-addon` installed `blender_mcp.py` into the Blender 4.2 user addons directory. The Codex `blender` stdio entry uses the absolute `C:\Users\tiger\.local\bin\uvx.exe` with argument `blender-mcp`. This is the third-party [ahujasid/blender-mcp](https://github.com/ahujasid/blender-mcp), not an official Blender plugin. Codex configuration follows [the official MCP instructions](https://developers.openai.com/codex/mcp/).

`start_mcp.py` enables the installed addon, sets telemetry consent false, saves user preferences and starts the localhost server for this authoring session. Launch Blender with the source blend and `--python ArtSource/Blender/start_mcp.py`. A read-only `get_scene_info` socket request to `127.0.0.1:9876` returned success: 6 body mesh groups, a camera and 3 lights. Current-session Codex tool discovery does not hot-load the new global entry; the addon/socket is verified, while an end-to-end Codex MCP tool call awaits a client reload. Asset generation itself used the deterministic local Blender batch script.
