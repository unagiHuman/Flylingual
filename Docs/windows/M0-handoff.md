# Windows M0 handoff

The baseline source snapshot contains Unity `Assets`, `Packages`, and `ProjectSettings` including `.meta` files, plus the Shiu Python source. Generated Unity state and macOS/Python caches are excluded.

Use `Contracts/protocol-existing.md` as the observed protocol description and `Contracts/fixtures/shiu_game_brain_controller_frames.jsonl` as the compact six-action fixture. The fixture is Shiu-specific evidence, not MaleCNS data.

The ignored Shiu connectome files must be transferred using the separate data archive and verified against its SHA-256 manifest. Do not transfer conda directories, `.dylib`, `.so`, Cython cache, Unity `Library`, or Unity build output.

No remote repository has been configured or published by the Mac M0 work.
