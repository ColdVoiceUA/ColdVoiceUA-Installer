# ColdVoiceUA — Resonance installer source review (lifecycle v3)

This separate directory is intended to accompany the Resonance Ukrainian voice-over installer. It does not replace the earlier Silent Hill: Townfall review directory.

## Scope and provenance

The generic bootstrap and PowerShell wizard are taken from the author's previously supplied CV2 current-source snapshot. The Resonance modules include the lifecycle v3 patch delivered on 2026-11-01: verified pristine-base selection, non-overwriting release output names and restore based on the saved installation state. The author supplied a read-only extraction from `ColdVoiceUA_Resonance_DEMO_v1.3.0.0.exe`. Its reported SHA-256 is `953f3278d7eb3b13e2d883a0cb6422c7d9e89234bfa140f813320e68fe48f07f` and reported size is 42,091,934 bytes. The extracted INSTALL.ps1 was independently compared with the rendered v3 source and matches after BOM/newline normalization. Every supplied review entry's size/SHA-256 was independently verified. The manifest contains 571 unique English-media replacement targets and its DEMO object/source ID sets match those replacements. The local extraction report states that all embedded WEM hashes were verified. The actual EXE and its WEM payload were not supplied to this workspace, so their hashes were not independently recomputed here. The exact extraction is preserved under `actual_exe_materials/`.

## Executed/runtime source

- `source/gamedub_release_bootstrap.cs`: WinForms bootstrap, embedded ZIP extraction, in-process Windows PowerShell hosting.
- `source/ResonancePckEngine.cs`: streaming AKPK/PCK rebuilding and exact SHA-256/size/layout checks; filesystem path checks.
- `source/gamedub_release_installer.ps1`: generic wizard; retained because the builder combines it with the Resonance runtime.
- `source/resonance_runtime.ps1`: Resonance overrides for install/update/restore. This is essential; the generic Townfall-era PS1 alone does not describe the Resonance installer.
- `source/gamedub_installer_texts.py`: renders the PS1/C# templates using manifest UI text settings.

## Build-time source

- `gamedub_resonance_release.py`: selects authored WEMs, constructs the manifest and payload, compiles the two C# sources, appends the payload ZIP.
- `resonance_pck.py`: reads the original PCK index and calculates the expected rebuilt layout/hash without shipping the original PCK.
- `resonance_release_lifecycle.py`: selects a verified original backup across installer revisions and chooses a new output name on collision.
- `gamedub_release_builder.py`: shared profile/icon helpers; not the complete Resonance builder by itself.
Studio-only DEMO chooser, waveform editor and audio-generation modules are outside this installer runtime package. The actual manifest records the selected replacement IDs and hashes. The reconstruction route accepts those exact replacements as inputs; it does not require regenerating them. This is not a complete runnable Studio distribution.

## Installer behavior

The embedded format is `[compiled C# host][payload ZIP][8-byte little-endian ZIP length][COLDVOICEZIPV01]`.

The Resonance payload contains authored UA WEM replacements, manifest, INSTALL.ps1 and icon assets. The original VO_MEDIA PCK is not included by the supplied Resonance builder. The runtime reads the user's existing original PCK and writes a rebuilt `SOUNDBANKS/VO_MEDIA.PC.PCK`, preserving untargeted entries from the original source. It verifies the exact base PCK and VO_STRUCTURE hashes and expected rebuilt output hash/size. This is not a file-copy-only mod: it replaces the game's live VO_MEDIA file after rebuilding.

The installer keeps `original.pck` and `state.json` under `.ColdVoiceInstaller/<slug>` in the selected game directory. Updates rebuild from the original backup and verify the existing installed file; they do not adopt an unknown modified file as original. Restore verifies the saved state, current-file/transaction hashes and backup hash; it does not require the launched release's base hash to equal the saved release's base hash. Restoring returns the backed-up original, not an arbitrary older UA dubbing release. Installation still requires a compatible verified game base.

The reviewed sources do not add antivirus exclusions or disable antivirus. The EXE uses an in-process PowerShell host; the developer-side collection BAT uses `powershell.exe -NoProfile -ExecutionPolicy Bypass` only to launch the read-only picker, without changing machine policy. No claim of antivirus certification or Nexus approval is made.

## Build route A — original authoring pipeline (Windows)

Requirements: Python 3.10+ with Tkinter, Pillow, Windows PowerShell 5.1 / System.Management.Automation, .NET Framework 4.x compiler (`Framework[64]/v4.0.30319/csc.exe`). Keep all `source/` files together.

1. Supply the actual profile (including game_root, game_exe, pck_target, base_pck, structure_path, project_dir, process_name, tested_version, installer_ui), original compatible game resources and authored WEMs.
2. Construct `reps={(1, source_id): ({'object_id': object_id}, Path(authored_wem)), ...}` using the actual manifest's object/source mapping. For DEMO, use exactly its selected manifest replacements; do not generate new voice content.
3. Call `gamedub_resonance_release.build_exe(profile, reps, counts, new_output_path)`. `counts` is the author's selection report. Original PCK data is used for expected output layout/hash but is not included in the EXE.
4. Exact icon, splash and UI settings must match the submitted release for a corresponding rebuild. Source alone cannot recreate the author's voice recordings or privately stored release inputs.

## Build route B — rebuild from the submitted payload without game resources

For the embedded EXE workflow, this package provides:

`python tools/rebuild_review.py --exe Submitted_Resonance.exe --splash OriginalSplash.png --output Rebuilt_Resonance.exe`

This verifies the submitted WEM hashes and compares embedded INSTALL.ps1 with the source-rendered runtime, recompiles the bootstrap plus ResonancePckEngine using .NET csc, and attaches the exact original payload ZIP. It does not execute the submitted EXE. Supply the original splash asset. The script refuses runtime mismatch and refuses to overwrite output. This route rebuilds the installer around the same payload; it does not regenerate voice assets. Compiler/resource metadata can differ: no byte-for-byte reproducibility guarantee is made. External `.data` installers require the original build route instead.

## Bind the review to the exact uploaded binary

Run `COLLECT_REVIEW.bat` and select the exact EXE uploaded to Nexus. The read-only tool:

- does not execute or load the submitted EXE;
- hashes it and verifies every manifest-listed embedded replacement's size/SHA-256;
- copies only manifest, rendered runtime and icon assets, plus the review report;
- compares rendered INSTALL.ps1 with the supplied v3 source;
- excludes all audio, original game files, project databases and credentials from the review ZIP.

For this reviewed release, that extraction/report is already included in `actual_exe_materials/`. Repeat collection only for a different EXE. Attach the corresponding report to the support request. A matching runtime hash does not prove C# binary/source equivalence. `SOURCE_SHA256.json` identifies this source snapshot; the generated `review_report.json` identifies the actual uploaded binary.

## Verification limits

Python syntax, v3 regression tests and synthetic embedded-container extraction were checked. No Windows/.NET compilation, actual EXE execution, malware scan or Nexus approval was performed here. The author separately confirmed install, update and restore working on their tested game after v3. This report does not extend that observation to arbitrary game versions or the currently uploaded EXE.
