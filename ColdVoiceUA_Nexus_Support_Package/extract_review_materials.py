"""Read-only EXE examination; never executes the installer."""
import argparse, hashlib, json, struct, zipfile
from pathlib import Path
a = argparse.ArgumentParser()
a.add_argument("exe")
a.add_argument("--output", default="ColdVoice_EXE_Review")
args = a.parse_args()
exe = Path(args.exe).resolve(strict=True)
out = Path(args.output).resolve()
archive = out.with_suffix(".zip")
if out.exists() or archive.exists():
    raise SystemExit("Output already exists; choose another --output directory.")
magic = b"COLDVOICEZIPV01"
with exe.open("rb") as f:
    f.seek(0, 2)
    length = f.tell()
    if length < len(magic) + 8: raise SystemExit("Invalid container")
    f.seek(-len(magic)-8, 2)
    trailer = f.read(8 + len(magic))
    size = struct.unpack("<Q", trailer[:8])[0]
    if trailer[8:] != magic or size < 100 or size > length-len(magic)-8:
        raise SystemExit("ColdVoice trailer not found")
h = hashlib.sha256()
with exe.open("rb") as f:
    for block in iter(lambda: f.read(4*1024*1024), b""): h.update(block)
names = ("manifest.json", "INSTALL.ps1", "INSTALLER.ico", "INSTALLER.png", "README_UA.txt")
# zipfile supports archives appended to executables; no executable code is loaded.
with zipfile.ZipFile(exe) as z:
    data = {}
    for name in names:
        entry = z.getinfo(name)
        if entry.file_size > 8*1024*1024: raise SystemExit("Oversized review entry")
        data[name] = z.read(entry)
    manifest = json.loads(data["manifest.json"])
source = Path(__file__).with_name("gamedub_release_installer.ps1")
same = (source.read_text(encoding="utf-8-sig").replace("\r\n", "\n") ==
        data["INSTALL.ps1"].decode("utf-8-sig").replace("\r\n", "\n"))
report = {
    "exe_name": exe.name, "exe_size": length, "exe_sha256": h.hexdigest(),
    "embedded_zip_size": size, "installer_source_matches_supplied_ps1": same,
    "entries": {n: {"size": len(v), "sha256": hashlib.sha256(v).hexdigest()}
                for n, v in data.items()},
    "game": manifest.get("game"), "tested_version": manifest.get("tested_version"),
    "targets": [row.get("target") for row in manifest.get("files", [])],
    "limits": "No EXE execution, antivirus scan, full payload check or C# correspondence proof."
}
out.mkdir(parents=True)
for name, value in data.items(): (out/name).write_bytes(value)
(out/"review_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED) as z:
    for item in out.iterdir(): z.write(item, item.name)
print("Saved:", archive)
print("Installer PS1 matches:", same)

