"""Recompile the reviewed bootstrap using the exact uploaded UA payload ZIP.
Requires Windows/.NET csc and the original splash asset; never reads the game.
Not a byte-for-byte reproducibility claim (compiler and ZIP/resource metadata vary).
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
from extract_review import extract, SOURCE, MAGIC, TRAILER_SIZE


def rebuild(exe,splash,output):
    if sys.platform!='win32':raise ValueError('Windows is required for .NET Framework compilation.')
    exe=Path(exe).resolve(strict=True);splash=Path(splash).resolve(strict=True);output=Path(output).resolve()
    if output.exists() or output==exe:raise ValueError('Output must be a new file; the uploaded EXE is never overwritten.')
    windows=Path(os.environ.get('SystemRoot',r'C:\Windows'))
    compiler=next((p for p in [windows/'Microsoft.NET/Framework64/v4.0.30319/csc.exe',windows/'Microsoft.NET/Framework/v4.0.30319/csc.exe'] if p.is_file()),None)
    if compiler is None:raise ValueError('.NET Framework csc.exe not found.')
    sys.path.insert(0,str(SOURCE))
    from gamedub_installer_texts import render_bootstrap
    with tempfile.TemporaryDirectory(prefix='ResonanceSourceRebuild_') as tmp:
        stage=Path(tmp)
        report,_=extract(exe,stage/'review')
        if not report['embedded_install_ps1_matches_supplied_source']:
            raise ValueError('The actual runtime does not match this source snapshot. Reconcile sources before rebuilding.')
        manifest=json.loads((stage/'review/manifest.json').read_text(encoding='utf-8-sig'))
        code=stage/'ResonanceSetup.cs'
        code.write_text(render_bootstrap((SOURCE/'gamedub_release_bootstrap.cs').read_text(encoding='utf-8-sig'),manifest['installer_ui']),encoding='utf-8-sig')
        host=stage/'bootstrap.exe'
        cmd=[str(compiler),'/nologo','/target:winexe','/platform:x64','/out:'+str(host),
             '/win32icon:'+str(stage/'review/INSTALLER.ico'),'/resource:'+str(splash)+',SplashImage',
             '/reference:System.Windows.Forms.dll','/reference:System.Drawing.dll','/reference:System.IO.Compression.dll',
             '/reference:System.IO.Compression.FileSystem.dll','/reference:System.Web.Extensions.dll',str(code),str(SOURCE/'ResonancePckEngine.cs')]
        run=subprocess.run(cmd,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
        if run.returncode:raise ValueError((run.stdout+run.stderr).decode(errors='replace'))
        zip_size=report['embedded_zip_size'];offset=exe.stat().st_size-TRAILER_SIZE-zip_size
        output.parent.mkdir(parents=True,exist_ok=True)
        created=False
        try:
            with output.open('xb') as dest:
                created=True
                with host.open('rb') as stream:shutil.copyfileobj(stream,dest)
                with exe.open('rb') as stream:
                    stream.seek(offset);remaining=zip_size
                    while remaining:
                        block=stream.read(min(4*1024*1024,remaining))
                        if not block:raise ValueError('Uploaded EXE changed during rebuild.')
                        dest.write(block);remaining-=len(block)
                dest.write(struct.pack('<Q',zip_size));dest.write(MAGIC)
        except Exception:
            if created:output.unlink(missing_ok=True)
            raise
    return output

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--exe',required=True);parser.add_argument('--splash',required=True);parser.add_argument('--output',required=True);args=parser.parse_args()
    try:print(rebuild(args.exe,args.splash,args.output))
    except Exception as exc:raise SystemExit(str(exc))
