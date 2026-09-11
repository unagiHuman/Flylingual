# Shiu native Windows preparation

2026-09-11 JST. Replay/Visual development can continue independently. This is environment preparation, not a successful SHIU LIVE result.

## Observed state

- Independent venv: `artifacts/windows-shiu/.venv` (Git ignored).
- Existing uv Python: `C:/Users/tiger/AppData/Roaming/uv/python/cpython-3.10-windows-x86_64-none/python.exe`, Python 3.10.12 x64.
- Installed and imported: Brian2 2.5.1, Cython 0.29.37, NumPy 1.24.4, pandas 1.4.3, joblib 1.2.0, pyarrow 11.0.0.
- `brain_server.py --help` succeeded; actual parser supports host, port, dataset, backend, seed, stimulus frequency, window, calibration source and run output.
- Visual Studio 2022 Community MSVC 14.39.33519 is present. The default shell has no `cl` on PATH; setuptools located the installed compiler during the unrestricted compile attempt.
- Minimal Cython test **failed** with MSVC `fatal error C1083: ... 'io.h': No such file or directory`. Standard `C:/Program Files (x86)/Windows Kits/10/Include` and `Lib` were not found. Windows SDK/UCRT headers and libraries need installation or a verified alternate SDK configuration. No SDK installer was launched.
- A sandboxed retry could not resolve `cl.exe`; that secondary failure is not evidence that MSVC is absent.
- Brian2 import initially needed permission to create its standard user `.brian` configuration directory. Compile artifacts use the explicit local cache below; no Mac cache or clang overrides were reused.

## Dependency provenance and reproduction

`environment-windows.yml` is a minimal Conda specification, not a lockfile and not itself tested with Conda. Python/Brian2/NumPy constraints come from `environment.yml`; Cython 0.29.37 comes from the handoff. Other explicit versions come from `environment_full.yml`, with its OS build strings removed. That older full inventory specifies NumPy 1.22.3 and Cython 0.29.33; these differences are deliberate handoff overrides, not proof of parity with the successful Mac runtime. No complete recent Mac resolved inventory was supplied. Notebook-only dependencies were omitted.

The actual test used uv, from the repository root:

```powershell
$env:UV_CACHE_DIR = Join-Path (Get-Location) 'artifacts/windows-shiu/uv-cache'
uv venv artifacts/windows-shiu/.venv --python 3.10
uv pip install --python artifacts/windows-shiu/.venv/Scripts/python.exe 'setuptools==67.8.0' 'wheel==0.38.4' 'numpy==1.24.*' 'Cython==0.29.37'
uv pip install --python artifacts/windows-shiu/.venv/Scripts/python.exe 'brian2==2.5.1' 'pandas==1.4.3' 'joblib==1.2.0' 'pyarrow==11.0.0' 'sympy==1.12' 'jinja2==2.11.3' 'markupsafe==1.1.1' --no-build-isolation
& artifacts/windows-shiu/.venv/Scripts/python.exe Brain/ShiuBaseline/run_cython_smoke_test.py --output artifacts/windows-shiu/cython_smoke_test.json --cache-dir artifacts/windows-shiu/cython_cache
& artifacts/windows-shiu/.venv/Scripts/python.exe Brain/ShiuBaseline/brain_server.py --help
```

All resolved packages are recorded in `artifacts/windows-shiu/pip-freeze.txt`; unconstrained transitives are observations, not invented baseline pins. Installation needed network access to PyPI. After SDK repair, rerun from a properly initialized x64 VS development environment and verify Cython success before any data-driven test. Do not silently switch to NumPy to label this gate passed.

## Missing data and next gate

The v783 paths resolved by unmodified `poc_config.py` are:

- `Brain/ShiuBaseline/Completeness_783.csv` — absent.
- `Brain/ShiuBaseline/Connectivity_783.parquet` — absent.
- Required separate data manifest with source URL/version, byte sizes, SHA-256 and selection/NT policy — not supplied. `Docs/mac/M0-baseline-manifest.md` explicitly says connectome inputs need a separate archive/manifest.

The calibration JSON is present at `Brain/ShiuBaseline/results/codex_run/motor_decoder_calibration.json`; SHA-256 is `d9ce02e1a853188649dcd96116c7aecf16275b298957271f0d7ae2cc21257e27`, matching M0. Its Mac absolute `source_result` is provenance, not a runtime load path.

Once the minimal Cython gate passes and the data manifest is verified, the actual supported server invocation is:

```powershell
& artifacts/windows-shiu/.venv/Scripts/python.exe Brain/ShiuBaseline/brain_server.py --host 127.0.0.1 --port 8765 --dataset v783 --backend cython --run-output artifacts/windows-shiu/brain_server_run.json
```

This command has **not** been run. First verify port ownership and use only one controlling client. Preserve seed 20260910, stimulus 100 Hz and 50 ms window defaults unless the baseline protocol calls for different settings. Do not reuse FlyWire IDs or calibration for MaleCNS.

## Evidence and limits

Local evidence: `artifacts/windows-shiu/cython_smoke_test.json` (failed MSVC compile, 7.48 s total), `cython_smoke_test_retry.json` (sandbox compiler discovery failure), `pip-freeze.txt`, `source-hashes.json`, and `compiler_failure.txt`. The first text log contains the earlier `.brian` permission failure; the JSON gives the subsequent compile result.

The existing smoke test contains only one neuron, no connectome and no synapses; two requested 1 ms windows, with the first failing before execution. No whole-brain initialization, six-action trial, TCP exchange or Unity operation was performed. Cold/warm timings, RSS, p95 step/E2E, N/E and Live success are unavailable. Neural equations, IDs, selection, calibration, motor decoder and Unity files were not changed by this preparation.

## SDK repair prepared, not executed

Read-only follow-up verified VS Community **17.9.7**, instance `99ddddf0`, and its cached catalog contains `Microsoft.VisualStudio.Component.Windows11SDK.22621` version `17.9.34511.75`. The standard Windows Kits directory contains 8.1 and NETFXSDK only; no alternate Windows 10/11 SDK was identified. No VS IDE or installer process was observed during this check.

The existing selection was saved to `artifacts/windows-shiu/vs-selected-before.json`; the additive `sdk-only.vsconfig` contains only `Microsoft.VisualStudio.Component.Windows11SDK.22621`. Microsoft's [component directory](https://learn.microsoft.com/en-us/visualstudio/install/workload-component-id-vs-build-tools?view=visualstudio) identifies it as Windows 11 SDK 10.0.22621.0. Microsoft's [installer CLI reference](https://learn.microsoft.com/en-us/visualstudio/install/use-command-line-parameters-to-install-visual-studio?view=vs-2022) documents `modify --add` and the administrator requirement for quiet/passive execution.

To avoid concurrent installation activity while Unity is being prepared, the installer was **not launched**. Once that activity finishes, from an Administrator PowerShell and the repository root:

```powershell
$sdkSetup = Start-Process -FilePath 'C:/Program Files (x86)/Microsoft Visual Studio/Installer/setup.exe' -ArgumentList 'modify --installPath "C:\Program Files\Microsoft Visual Studio\2022\Community" --add Microsoft.VisualStudio.Component.Windows11SDK.22621 --removeOos false --quiet --norestart --noUpdateInstaller' -WindowStyle Hidden -PassThru -Wait
$sdkSetup.ExitCode
```

This requests only SDK addition, keeps unsupported components, avoids forced app closure/reboot, and fails if an installer update is required instead of updating it automatically. Administrator elevation may show UAC and needs the user's interaction. Do not treat a returned setup process alone as successful installation: retain `%TEMP%/dd_setup*` logs, check the exit status and installed SDK headers/libraries, compare the selected component inventory to the saved snapshot, then rerun the minimal Cython test. No existing component removal or Visual Studio product update is authorized by this recipe.
