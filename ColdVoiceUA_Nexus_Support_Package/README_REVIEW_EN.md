# ColdVoiceUA installer source review

The four source files supplied by the author on 2026-10-09 are preserved without modifications. This is a review package, not a Studio update or localization payload.

## Source roles

- gamedub_release_bootstrap.cs: Windows Forms bootstrap, ZIP extraction, in-process PowerShell host.
- gamedub_release_installer.ps1: install/upgrade/restore wizard and filesystem operations.
- gamedub_release_builder.py: profile validation, hashing, ZIP construction, C# compilation and EXE assembly.
- gamedub_demo_builder.py: selected-line demo integration; depends on the complete Studio application and its audio build engine.

## Observed runtime

Container: [C# executable][ZIP][8-byte little-endian ZIP length][COLDVOICEZIPV01].
The bootstrap extracts to a unique ColdVoiceSetup_* temporary folder, checks archive entry paths, loads System.Management.Automation and runs INSTALL.ps1 in an STA runspace inside the process. It does not launch powershell.exe for the EXE workflow.
The archive additionally contains INSTALL.bat, which uses powershell.exe -NoProfile -ExecutionPolicy Bypass for the separate unpacked ZIP workflow; it does not change system-wide policy.

The wizard checks the game marker/process, verifies payload SHA-256 hashes, stores backups and state in .ColdVoiceInstaller/<slug> inside the selected game root, and copies manifest targets.
Townfall targets include Mods/ColdVoice banks, replacements for native FMOD banks and pakchunk1-Windows.pak, and additional text/menu override files. Installation DOES replace existing game files.
Restore validates backups, restores originals, removes tracked additions and empty tracked directories, and removes state. Upgrades preserve first-install originals and use a rollback journal.
The supplied runtime sources show no network downloads, telemetry, registry writes, scheduled-task/service creation or antivirus exclusions. This observation is not a malware certification of the uploaded binary.

## Build with the original builder on Windows

Requirements: Python 3.10+; Pillow; Windows PowerShell 5.1; .NET Framework 4.8 with Framework/Framework64 v4.0.30319 csc.exe. This builder does not require Visual Studio.

1. Put release_builder.py, bootstrap.cs and installer.ps1 together, retaining their original gamedub_ filenames.
2. Supply the saved installer_game_profiles.json, exact installer ICO and splash image. Profiles can explicitly specify installer_icon and splash_image; otherwise the builder expects gamedub_installer_default.ico/.png alongside its source.
3. Prepare the game root with every source file from the profile. For a demo, run the original Studio demo action first to rebuild ONLY the selected dialogue lines. A full-version prepared root would package a full version.
4. Load the actual profile via load_profiles(studio_folder), select slug townfall, and retain its tested_version. For the demo, its name is the original name plus " — Demo".
5. Call build_exe(profile, prepared_game_root, output_exe) imported from gamedub_release_builder. Output must be outside the game directory.

The builder uses csc /nologo /target:winexe /platform:anycpu, embeds the ICO and SplashImage resource, and references System.Windows.Forms.dll, System.Drawing.dll, System.IO.Compression.dll and System.IO.Compression.FileSystem.dll.
It runs --verify-icon, --verify-host and --verify-installer checks, then appends its validated payload ZIP, length and magic.
The actual EXE materials now include the manifest, embedded installer script, ICO and icon-preview PNG. The original splash image, saved Studio profile and prepared localization payload are still not included. The four source files alone cannot regenerate selected-line localization banks.

## Read-only verification of the actual quarantined EXE

Run: python .\extract_review_materials.py "C:\path\ColdVoiceUA_Demo.exe"

This produces ColdVoice_EXE_Review.zip containing the actual embedded manifest, INSTALL.ps1, icon assets, README, an EXE SHA-256 hash and a PS1 comparison report. No game payload is copied and the EXE is never executed. Python standard library only.
A matching PS1 is not proof of C# source/binary equivalence. The original splash and complete build inputs are needed for corresponding builds.

## Review limits

Python syntax and the extractor's synthetic-container behavior were checked. No Windows C# compilation, PowerShell execution, gameplay test or antivirus certification was performed in this Linux environment. The complete quarantined EXE has not been supplied here. An author-generated read-only extraction report identifies it as 606244628 bytes with SHA-256 b375f49779e4e4e1c223a2f352b3df838767d84f063ab82d1be903842072572b. The extracted INSTALL.ps1 was independently compared with the supplied PowerShell source and matches after decoding BOM/newline normalization. All supplied extracted-entry hashes and sizes were independently checked. C# binary/source correspondence, antivirus status and complete payload contents remain unverified. Nexus support decides approval.

