"""Read an embedded ColdVoice installer without executing or loading the EXE."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import zipfile

SOURCE=Path(__file__).resolve().parents[1]/'source'
MAGIC=b'COLDVOICEZIPV01'
TRAILER_SIZE=8+len(MAGIC)


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(4*1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def expected_runtime():
    sys.path.insert(0,str(SOURCE))
    import gamedub_resonance_release as release
    from gamedub_installer_texts import render_powershell
    return render_powershell(release.combined_ps((SOURCE/'gamedub_release_installer.ps1').read_text(encoding='utf-8-sig')))


def normalize(text):return text.lstrip('\ufeff').replace('\r\n','\n')


def extract(exe,output):
    exe=Path(exe).resolve(strict=True);output=Path(output).resolve()
    if output.exists() or output.with_suffix('.zip').exists():raise ValueError('Output exists. Choose another output name.')
    length=exe.stat().st_size
    if length<TRAILER_SIZE:raise ValueError('Not an embedded ColdVoice EXE.')
    with exe.open('rb') as f:
        f.seek(-TRAILER_SIZE,2);trailer=f.read(TRAILER_SIZE)
        size=struct.unpack('<Q',trailer[:8])[0]
        if trailer[8:]!=MAGIC or not 100<=size<=length-TRAILER_SIZE:raise ValueError('Embedded ZIP trailer not found. This tool targets the embedded EXE workflow, not external .data packages.')
    data={}
    with zipfile.ZipFile(exe) as z:
        names=z.namelist()
        if len(names)!=len(set(names)):raise ValueError('Duplicate archive entries.')
        for name in ('manifest.json','INSTALL.ps1','INSTALLER.ico','INSTALLER.png'):
            entry=z.getinfo(name)
            if entry.file_size>32*1024*1024:raise ValueError('Oversized review metadata.')
            data[name]=z.read(entry)
        manifest=json.loads(data['manifest.json'].decode('utf-8-sig'))
        if manifest.get('mode')!='resonance-approved-wem-v1':raise ValueError('This is not the Resonance PCK installer.')
        expected=[]
        for row in manifest['pck']['replacements']:
            name=row['payload']
            if not isinstance(name,str) or not name.startswith('UA/') or '..' in name.split('/') or '\\' in name or ':' in name:raise ValueError('Unexpected replacement path.')
            entry=z.getinfo(name)
            if entry.file_size!=row['size']:raise ValueError('WEM size mismatch: '+name)
            h=hashlib.sha256()
            with z.open(entry) as stream:
                for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
            if h.hexdigest().lower()!=row['sha256'].lower():raise ValueError('WEM hash mismatch: '+name)
            expected.append(name)
        allowed={'manifest.json','INSTALL.ps1','INSTALLER.ico','INSTALLER.png',*expected}
        unexpected=[n for n in names if n not in allowed and not n.endswith('/')]
        if unexpected:raise ValueError('Unexpected embedded files: '+str(unexpected))
    same=normalize(data['INSTALL.ps1'].decode('utf-8-sig'))==normalize(expected_runtime())
    report={'exe_name':exe.name,'exe_sha256':digest(exe),'exe_size':length,'embedded_zip_size':size,
            'game':manifest.get('game'),'tested_version':manifest.get('tested_version'),
            'mode':manifest.get('mode'),'replacement_count':len(expected),
            'all_replacement_hashes_verified':True,'embedded_install_ps1_matches_supplied_source':same,
            'review_entries':{n:{'size':len(v),'sha256':hashlib.sha256(v).hexdigest()} for n,v in data.items()},
            'scope':'Metadata only in review ZIP. No WEM audio, original PCK, project database or credentials copied.',
            'limits':'EXE not executed. No antivirus verdict or C# binary/source correspondence proof.'}
    output.mkdir(parents=True)
    for name,raw in data.items():(output/name).write_bytes(raw)
    (output/'review_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    with zipfile.ZipFile(output.with_suffix('.zip'),'x',zipfile.ZIP_DEFLATED) as z:
        for f in sorted(output.iterdir()):z.write(f,f.name)
    return report,output.with_suffix('.zip')

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('exe');a.add_argument('--output',default='Resonance_EXE_Review');args=a.parse_args()
    try:
        report,out=extract(args.exe,args.output)
        print('Saved:',out)
        print('Runtime matches supplied source:',report['embedded_install_ps1_matches_supplied_source'])
        if not report['embedded_install_ps1_matches_supplied_source']:print('DO NOT claim a matching review snapshot: send this report for source reconciliation.')
    except Exception as exc:raise SystemExit(str(exc))
