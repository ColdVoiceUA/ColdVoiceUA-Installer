from pathlib import Path
import hashlib
import importlib.util
import json
import struct
import tempfile
import unittest
import zipfile
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import extract_review as tool

class ReviewTests(unittest.TestCase):
    def fixture(self,root,runtime=None,corrupt=False,extra=False):
        payload=b'RIFF0000WAVEua'
        manifest={'mode':'resonance-approved-wem-v1','game':'Resonance DEMO','tested_version':'1.3.0.0','pck':{'replacements':[{'payload':'UA/17.wem','size':len(payload),'sha256':hashlib.sha256(payload).hexdigest()}]}}
        archive=root/'payload.zip'
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_STORED) as z:
            z.writestr('manifest.json',json.dumps(manifest))
            z.writestr('INSTALL.ps1',runtime if runtime is not None else tool.expected_runtime())
            z.writestr('INSTALLER.ico',b'icon');z.writestr('INSTALLER.png',b'png')
            z.writestr('UA/17.wem',b'bad' if corrupt else payload)
            if extra:z.writestr('original.pck',b'not allowed')
        raw=archive.read_bytes();exe=root/'Submitted.exe';exe.write_bytes(b'MZsynthetic-host'+raw+struct.pack('<Q',len(raw))+tool.MAGIC)
        return exe
    def test_matching_runtime_hashes_and_no_audio_copied(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);exe=self.fixture(r);before=exe.read_bytes();report,out=tool.extract(exe,r/'review')
            self.assertTrue(report['embedded_install_ps1_matches_supplied_source'])
            self.assertTrue(report['all_replacement_hashes_verified'])
            with zipfile.ZipFile(out) as z:self.assertFalse(any(n.startswith('UA/') or n.endswith('.wem') for n in z.namelist()))
            self.assertEqual(exe.read_bytes(),before)
            with self.assertRaises(ValueError):tool.extract(exe,r/'review')
    def test_mismatched_runtime_reported(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);exe=self.fixture(r,'different runtime');report,_=tool.extract(exe,r/'review')
            self.assertFalse(report['embedded_install_ps1_matches_supplied_source'])
    def test_bad_payload_and_unexpected_original_rejected(self):
        for kwargs in ({'corrupt':True},{'extra':True}):
            with tempfile.TemporaryDirectory() as d:
                r=Path(d);exe=self.fixture(r,**kwargs)
                with self.assertRaises(ValueError):tool.extract(exe,r/'review')
                self.assertFalse((r/'review').exists())

if __name__=='__main__':unittest.main()
