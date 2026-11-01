"""Portable, profile-driven release packager for GameDub."""
import hashlib
import json
import os
import re
import io
import struct
import zipfile
from pathlib import Path

PROFILE_FILE = 'installer_game_profiles.json'
TOWNFALL = 'Silent Hill: Townfall'


def _relative(value):
    value = str(value).replace('\\', '/').strip('/')
    parts = value.split('/')
    if not value or any(p in ('', '.', '..') or ':' in p for p in parts):
        raise ValueError('Небезпечний відносний шлях: ' + value)
    return '/'.join(parts)


def townfall_profile():
    return {
        'name': TOWNFALL,
        'slug': 'townfall',
        'game_marker': 'Townfall/Content/Paks/pakchunk1-Windows.pak',
        'process_name': 'Townfall-Win64-Shipping',
        'tested_version': '',
        'files': [
            {'source': 'Townfall/Mods/ColdVoice/Dialogue_JP.bank', 'target': 'Townfall/Mods/ColdVoice/Dialogue_JP.bank'},
            {'source': 'Townfall/Mods/ColdVoice/Cinematics_JP.bank', 'target': 'Townfall/Mods/ColdVoice/Cinematics_JP.bank'},
            {'source': 'Townfall/Mods/ColdVoice/Dialogue_JP.bank', 'target': 'Townfall/Content/FMOD/Banks/Desktop/Dialogue_JP.bank'},
            {'source': 'Townfall/Mods/ColdVoice/Cinematics_JP.bank', 'target': 'Townfall/Content/FMOD/Banks/Desktop/Cinematics_JP.bank'},
            {'source': 'Townfall/Content/Paks/~mods/zzz_GameDubUA-DLOC_P.pak', 'target': 'Townfall/Content/Paks/~mods/zzz_GameDubUA-DLOC_P.pak'},
            {'source': 'Townfall/Content/Paks/~mods/zzz_ColdVoice-Menu_P.pak', 'target': 'Townfall/Content/Paks/~mods/zzz_ColdVoice-Menu_P.pak'},
            {'source': 'Townfall/Content/Paks/pakchunk1-Windows.pak', 'target': 'Townfall/Content/Paks/pakchunk1-Windows.pak'},
            *[{'source': 'Townfall/Content/Paks/pakchunk9999-GameDubUA-Windows_P.' + ext,
               'target': 'Townfall/Content/Paks/pakchunk9999-GameDubUA-Windows_P.' + ext}
              for ext in ('pak', 'utoc', 'ucas')],
        ],
    }


def load_profiles(folder):
    path = Path(folder) / PROFILE_FILE
    obj = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {'profiles': [townfall_profile()]}
    profiles = obj.get('profiles', [])
    # Profiles saved by V138-V140 omitted the root DLOC and Zen menu files.
    # Add exact required rows without removing project-specific extensions.
    for profile in profiles if isinstance(profiles, list) else []:
        if profile.get('slug') == 'townfall':
            present = {str(x.get('target', '')).casefold() for x in profile.get('files', [])}
            for row in townfall_profile()['files']:
                if row['target'].casefold() not in present:
                    profile.setdefault('files', []).append(dict(row))
    if not isinstance(profiles, list):
        raise ValueError('profiles має бути списком')
    return profiles


def save_profiles(folder, profiles):
    path = Path(folder) / PROFILE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps({'schema': 1, 'profiles': profiles}, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, path)


def _sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def _installer_icon_assets(path):
    """Return Windows-compatible ICO (XOR+AND masks) and a UI preview PNG."""
    from PIL import Image
    with Image.open(path) as source:
        source.load()
        image = source.convert('RGBA')
    entries = []
    for size in (16, 32, 48, 64, 128, 256):
        frame = image.resize((size, size), Image.Resampling.LANCZOS)
        # DIB height contains XOR and AND planes; both are bottom-up.
        header = struct.pack('<IiiHHIIiiII', 40, size, size * 2, 1, 32,
                             0, size * size * 4, 0, 0, 0, 0)
        pixels = b''.join(frame.crop((0, y, size, y + 1)).tobytes('raw', 'BGRA')
                          for y in range(size - 1, -1, -1))
        mask = b''.join(bytes(sum((0x80 >> bit) for bit in range(8)
                                  if frame.getpixel((byte * 8 + bit, y))[3] < 128)
                              for byte in range(size // 8))
                        for y in range(size - 1, -1, -1))
        entries.append((size, header + pixels + mask))
    offset = 6 + len(entries) * 16
    ico = bytearray(struct.pack('<HHH', 0, 1, len(entries)))
    for size, data in entries:
        ico += struct.pack('<BBBBHHII', size if size < 256 else 0,
                           size if size < 256 else 0, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    for _, data in entries:
        ico += data
    preview = io.BytesIO()
    image.resize((64, 64), Image.Resampling.LANCZOS).save(preview, format='PNG')
    return bytes(ico), preview.getvalue()


def _validate_fmod_bank(path):
    """Read-only RIFF/SND extent preflight; catches the pre-V213 corruption.

    This is a container check, not proof of FMOD routing or gameplay.
    """
    length = path.stat().st_size
    with path.open('rb') as stream:
        header = stream.read(12)
        if len(header) != 12 or header[:4] != b'RIFF' or struct.unpack_from('<I', header, 4)[0] + 8 != length:
            raise ValueError('Некоректна RIFF-довжина банку: ' + path.name + '. Перебудуйте банки поточною версією GameDub.')
        position, sounds = 12, 0
        while position + 8 <= length:
            stream.seek(position)
            tag, size = struct.unpack('<4sI', stream.read(8))
            stop = position + 8 + size
            if stop > length:
                raise ValueError('Чанк виходить за межі банку: ' + path.name)
            if tag == b'SND ':
                stream.seek(position + 8)
                lead = stream.read(min(128, size))
                relative = lead.find(b'FSB5')
                if relative < 0:
                    raise ValueError('SND без FSB5: ' + path.name)
                offset = position + 8 + relative
                stream.seek(offset)
                main = stream.read(28)
                if len(main) != 28:
                    raise ValueError('Обрізаний FSB5: ' + path.name)
                version, count, headers, names, data, codec = struct.unpack_from('<6I', main, 4)
                base = {0: 64, 1: 60}.get(version)
                if base is None or offset + base + headers + names + data != stop:
                    raise ValueError('Довжини FSB5/SND не збігаються: ' + path.name + '. Перебудуйте банки поточною версією GameDub.')
                sounds += 1
            position = stop + (size & 1)
        if position != length or not sounds:
            raise ValueError('Неповна структура аудіобанку: ' + path.name)


def build_release(profile, source_root, output_zip):
    tested_version = str(profile.get('tested_version', '')).strip()
    if not tested_version or len(tested_version) > 100 or any(ord(c) < 32 for c in tested_version):
        raise ValueError('Вкажіть перевірені збірки гри в профілі інсталятора (до 100 символів, одним рядком).')
    root = Path(source_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError('Папка джерела має бути папкою гри')
    marker = _relative(profile['game_marker'])
    if not (root / marker).is_file():
        raise FileNotFoundError('Не знайдено маркер гри: ' + marker)
    files = profile['files']
    if not files:
        raise ValueError('Профіль не має файлів')
    sources = {}
    rows = []
    targets = set()
    for row in files:
        src, dst = _relative(row['source']), _relative(row['target'])
        if dst.casefold() in targets:
            raise ValueError('Повторення цільового шляху: ' + dst)
        targets.add(dst.casefold())
        path = (root / src).resolve(strict=True)
        if not path.is_file() or not path.is_relative_to(root):
            raise ValueError('Неприпустиме джерело: ' + src)
        if not path.stat().st_size:
            raise ValueError('Порожній файл: ' + src)
        sources[src] = path
        rows.append({'payload': 'Payload/' + src, 'target': dst, 'sha256': _sha(path), 'size': path.stat().st_size})
    if profile.get('slug') == 'townfall':
        required = {x['target'] for x in townfall_profile()['files']}
        if not required.issubset({r['target'] for r in rows}):
            raise ValueError('Townfall вимагає банки, FMOD paths, live DLOC, root menu triplet та overrides')
        bank_dir = root / 'Townfall/Mods/ColdVoice'
        if {p.name for p in bank_dir.iterdir() if p.is_file()} != {'Dialogue_JP.bank', 'Cinematics_JP.bank'}:
            raise ValueError('Mods/ColdVoice повинен містити рівно два банки')
        for name in ('Dialogue_JP.bank', 'Cinematics_JP.bank'):
            _validate_fmod_bank(bank_dir / name)
            live = root / 'Townfall/Content/FMOD/Banks/Desktop' / name
            if not live.is_file() or _sha(live) != _sha(bank_dir / name):
                raise ValueError('FMOD live bank не збігається з Mods/ColdVoice: ' + name)
        # Current live text may have been updated after the last voice install.
        override = root / 'Townfall/Content/Paks/~mods/zzz_GameDubUA-DLOC_P.pak'
        live_text = root / marker
        if _sha(override) != _sha(live_text):
            raise ValueError('DLOC override і live pakchunk1 відрізняються; спочатку синхронізуйте субтитри')
        menu = root / 'Townfall/Content/Paks'
        if not all((menu / ('pakchunk9999-GameDubUA-Windows_P.' + ext)).is_file()
                   for ext in ('pak', 'utoc', 'ucas')):
            raise ValueError('Бракує повного root Zen menu triplet; запустіть поточну збірку Townfall')
    baseline = []
    if profile.get('slug') == 'townfall':
        candidate = next((root / ('Townfall/Content/Paks/' + name) for name in ('pakchunk1-Windows.pak.ORIGINAL_BACKUP', 'pakchunk1-Windows.ORIGINAL_BACKUP.pak') if (root / ('Townfall/Content/Paks/' + name)).is_file()), None)
        if candidate is not None:
            baseline.append({'target': marker, 'sha256': _sha(candidate)})
    originals = []
    if profile.get('slug') == 'townfall':
        originals = [
            {'target': 'Townfall/Content/FMOD/Banks/Desktop/Dialogue_JP.bank', 'sha256': '7cf54154ed0c0247a955c8042846fa972e9707c7f6c8289fbff51502f8fdf86d'},
            {'target': 'Townfall/Content/FMOD/Banks/Desktop/Cinematics_JP.bank', 'sha256': '877391f646d2065ece3f6009cb07606a000f1ce0072b971c474304f17f0d4990'},
        ]
    require_absent = [r['target'] for r in rows if r['target'].startswith('Townfall/Mods/ColdVoice/') or r['target'].startswith('Townfall/Content/Paks/~mods/') or 'pakchunk9999-GameDubUA-Windows_P.' in r['target']] if profile.get('slug') == 'townfall' else []
    manifest = {'schema': 1, 'originals': originals, 'baseline': baseline, 'require_absent': require_absent, 'game': profile['name'], 'tested_version': tested_version, 'slug': re.sub('[^a-z0-9_-]', '_', str(profile.get('slug', 'game')).lower()),
                'marker': marker, 'process': str(profile.get('process_name', '')), 'files': rows}
    # COLDVOICE_INSTALLER_CONSTRUCTOR_V1
    from gamedub_installer_texts import catalog, validate
    ps_template = Path(__file__).with_name('gamedub_release_installer.ps1').read_text(encoding='utf-8-sig')
    cs_template = Path(__file__).with_name('gamedub_release_bootstrap.cs').read_text(encoding='utf-8-sig')
    manifest['installer_ui'] = validate(profile.get('installer_ui'), catalog(ps_template, cs_template))
    output = Path(output_zip).resolve()
    if output == root or output.is_relative_to(root):
        raise ValueError('Збережіть інсталятор поза папкою гри')
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(output.name + '.tmp')
    try:
        with zipfile.ZipFile(temp, 'w', allowZip64=True) as z:
            for src, path in sources.items():
                z.write(path, 'Payload/' + src, compress_type=zipfile.ZIP_STORED if path.suffix.lower() == '.bank' else zipfile.ZIP_DEFLATED)
            z.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
            z.writestr('INSTALL.ps1', __import__('gamedub_installer_texts').render_archive_script(Path(__file__).with_name('gamedub_release_installer.ps1').read_text(encoding='utf-8-sig').encode('utf-8-sig')))
            icon = Path(profile.get('installer_icon') or Path(__file__).with_name('gamedub_installer_default.ico'))
            if not icon.is_file() or icon.read_bytes()[:4] != b'\0\0\1\0':
                raise ValueError('Іконка має бути чинним файлом .ico')
            icon_bytes, icon_preview = _installer_icon_assets(icon)
            z.writestr('INSTALLER.ico', icon_bytes)
            z.writestr('INSTALLER.png', icon_preview)
            z.writestr('INSTALL.bat', b'@echo off\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0INSTALL.ps1"\r\npause\r\n')
            z.writestr('README_UA.txt', ('GameDub / ColdVoice — ' + profile['name'] + '\nРозпакуйте ZIP повністю. Запустіть INSTALL.bat. Виберіть папку чистої гри, потім «Встановити». Для повернення використайте «Відновити до оригіналу». Закрийте гру перед обома діями.\n').encode('utf-8'))
        with zipfile.ZipFile(temp) as z:
            bad = z.testzip()
            if not z.read('INSTALLER.ico').startswith(b'\0\0\1\0'):
                raise ValueError('Installer window icon missing')
            if not z.read('INSTALL.ps1').startswith(b'\xef\xbb\xbf'):
                raise ValueError('PowerShell bootstrap missing UTF-8 BOM')
            if bad:
                raise ValueError('Помилка ZIP: ' + bad)
        os.replace(temp, output)
    finally:
        if temp.exists():
            temp.unlink()
    return output, manifest


def build_exe(profile, source_root, output_exe):
    """Compile a Windows GUI EXE, append the verified payload ZIP in-process."""
    import shutil
    import subprocess
    import sys
    import tempfile
    if sys.platform != 'win32':
        raise RuntimeError('EXE збирається у Windows, де встановлена GameDub Studio.')
    output = Path(output_exe).resolve()
    source_absolute = Path(source_root).resolve()
    if output == source_absolute or output.is_relative_to(source_absolute):
        raise ValueError('Збережіть інсталятор поза папкою гри')
    if output.suffix.lower() != '.exe':
        raise ValueError('Назва результату має закінчуватися .exe')
    output.parent.mkdir(parents=True, exist_ok=True)
    windows = Path(os.environ.get('SystemRoot', r'C:\Windows'))
    candidates = [windows / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe',
                  windows / 'Microsoft.NET/Framework/v4.0.30319/csc.exe']
    compiler = next((x for x in candidates if x.is_file()), None)
    if compiler is None:
        raise RuntimeError('Не знайдено .NET Framework 4.x C# compiler. Потрібен встановлений .NET Framework 4.8.')
    icon = Path(profile.get('installer_icon') or Path(__file__).with_name('gamedub_installer_default.ico'))
    splash = Path(profile.get('splash_image') or Path(__file__).with_name('gamedub_installer_default.png'))
    if not icon.is_file() or icon.read_bytes()[:4] != b'\0\0\1\0':
        raise ValueError('Іконка має бути чинним файлом .ico')
    if not splash.is_file() or splash.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.bmp'):
        raise ValueError('Стартова картинка має бути PNG, JPG або BMP')
    with tempfile.TemporaryDirectory(prefix='ColdVoiceBuild_') as td:
        stage = Path(td)
        # Give csc a legacy ICO with complete XOR and transparency mask planes.
        try:
            compiled_icon = stage / 'ColdVoice.ico'
            compiled_icon.write_bytes(_installer_icon_assets(icon)[0])
        except Exception as exc:
            raise ValueError('Не вдалося підготувати іконку .ico для EXE: ' + str(exc)) from exc
        archive, manifest = build_release(profile, source_root, stage / 'payload.zip')
        bootstrap = stage / 'bootstrap.exe'
        source = Path(__file__).with_name('gamedub_release_bootstrap.cs')
        from gamedub_installer_texts import render_bootstrap
        template = Path(source).read_text(encoding='utf-8-sig')
        source = Path(stage) / 'bootstrap_texts.cs'
        source.write_text(render_bootstrap(template, manifest['installer_ui']), encoding='utf-8-sig')
        command = [str(compiler), '/nologo', '/target:winexe', '/platform:anycpu',
                   '/out:' + str(bootstrap), '/win32icon:' + str(compiled_icon),
                   '/resource:' + str(splash) + ',SplashImage',
                   '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll',
                   '/reference:System.IO.Compression.dll', '/reference:System.IO.Compression.FileSystem.dll',
                   str(source)]
        result = subprocess.run(command, cwd=str(stage), stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=120, text=True,
                                errors='replace', creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode or not bootstrap.is_file():
            raise RuntimeError('Не вдалося зібрати Windows EXE: ' + (result.stdout or '')[-1800:])
        icon_check = subprocess.run([str(bootstrap), '--verify-icon', str(compiled_icon)],
                                    cwd=str(stage), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
        if icon_check.returncode:
            raise RuntimeError('Іконка не вбудована у зібраний EXE або не збігається з вибраним .ico. '
                               'Спробуйте зберегти іконку у звичайному форматі ICO з розміром 32×32.')
        host_check = subprocess.run([str(bootstrap), '--verify-host'], cwd=str(stage),
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
        if host_check.returncode:
            raise RuntimeError('Не вдалося запустити PowerShell 5.1 усередині ColdVoice EXE. '
                               'Збірку зупинено, щоб не створити майстер із чужою іконкою панелі задач.')
        installer_check = subprocess.run([str(bootstrap), '--verify-installer',
                                          str(Path(__file__).with_name('gamedub_release_installer.ps1'))],
                                         cwd=str(stage), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         timeout=120, creationflags=subprocess.CREATE_NO_WINDOW)
        if installer_check.returncode:
            raise RuntimeError('Перевірка PowerShell та коду вибору папки не пройшла. EXE не створено.')
        temp = output.with_name(output.name + '.coldvoice-tmp')
        if temp.exists():
            raise RuntimeError('Існує незавершений EXE: ' + str(temp))
        magic = b'COLDVOICEZIPV01'
        try:
            with temp.open('wb') as dest, bootstrap.open('rb') as executable, archive.open('rb') as payload:
                shutil.copyfileobj(executable, dest, 4 * 1024 * 1024)
                shutil.copyfileobj(payload, dest, 4 * 1024 * 1024)
                dest.write(archive.stat().st_size.to_bytes(8, 'little'))
                dest.write(magic)
            with temp.open('rb') as result_file:
                if result_file.read(2) != b'MZ':
                    raise ValueError('Помилка EXE: відсутній PE заголовок')
                result_file.seek(-len(magic), 2)
                if result_file.read(len(magic)) != magic:
                    raise ValueError('Помилка EXE: відсутній комплект')
            os.replace(temp, output)
            # Explorer may keep an earlier icon for the same .exe path. Announce
            # the actual newly written file and invalidate the shell icon cache.
            try:
                import ctypes
                shell = ctypes.windll.shell32
                shell.SHChangeNotify(0x00002000, 0x0005, str(output), None)
                shell.SHChangeNotify(0x08000000, 0, None, None)
            except Exception:
                pass
        finally:
            if temp.exists():
                temp.unlink()
        return output, manifest
