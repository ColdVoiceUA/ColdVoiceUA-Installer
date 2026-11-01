"""Keep release outputs and resolve the verified pristine PCK across dubbing updates."""
import copy
import json
from pathlib import Path, PureWindowsPath
from datetime import datetime
import uuid
from resonance_pck import sha, parse

MODE='resonance-approved-wem-v1'


def under(root, relative):
    raw=str(relative or '')
    win=PureWindowsPath(raw)
    if not raw or win.drive or win.root or any(p in ('..','.') for p in raw.replace('\\','/').split('/')):
        raise ValueError('Некоректний відносний шлях: '+raw)
    root=Path(root).resolve(strict=True)
    path=root.joinpath(*raw.replace('\\','/').split('/'))
    # Match runtime: no redirecting links, including missing child paths.
    p=path
    while p!=root:
        if p.is_symlink():raise ValueError('Символічне посилання у шляху гри.')
        p=p.parent
    path.resolve().relative_to(root)
    return path


def same_target(left,right):
    return str(left).replace('\\','/').casefold()==str(right).replace('\\','/').casefold()


def pristine_profile(profile,log=print):
    result=copy.deepcopy(profile)
    root=Path(profile['game_root']).resolve(strict=True)
    target=under(root,profile['pck_target'])
    state_root=under(root,'.ColdVoiceInstaller')
    candidates=[]
    if state_root.is_dir():
        for folder in state_root.iterdir():
            state_file=folder/'state.json'
            if not state_file.is_file():continue
            # Restrict all state and backup reads to this game's real tree.
            state_file=under(root,state_file.relative_to(root).as_posix())
            try:state=json.loads(state_file.read_text(encoding='utf-8-sig'))
            except (ValueError,UnicodeError) as exc:raise ValueError('Не читається стан установки: '+str(state_file)) from exc
            if state.get('mode')==MODE and same_target(state.get('target'),profile['pck_target']):
                candidates.append((folder,state))
    if len(candidates)>1:raise ValueError('Для одного VO_MEDIA знайдено кілька станів установки. Вибір оригіналу неоднозначний.')
    if candidates:
        folder,state=candidates[0]
        if state.get('schema')!=1 or state.get('phase') not in ('installed','writing','restoring'):
            raise ValueError('Невідомий стан установки; резерв не змінено.')
        original=under(root,(folder/'original.pck').relative_to(root).as_posix())
        expected=str(state.get('base_sha256') or '').lower()
        if len(expected)!=64 or any(c not in '0123456789abcdef' for c in expected):raise ValueError('Немає коректного SHA256 оригіналу в state.json.')
        if not original.is_file() or sha(original)!=expected:
            raise ValueError('Резерв original.pck відсутній або пошкоджений. Поточний озвучений PCK не буде використано замість оригіналу.')
        # A different slug would make a new EXE fail to find the old backup.
        if folder.name!=profile['slug']:
            raise ValueError('Стан знайдено в профілі '+folder.name+'. Використайте цей slug замість '+profile['slug']+'.')
        parse(original)
        result['base_pck']=str(original)
        log('Оригінальна основа: перевірений original.pck зі збереженого стану установки.')
        return result
    configured=Path(profile['base_pck']).resolve(strict=True)
    native=target.with_name(target.name+'.gamedub_original')
    # Standard GameDub backup belongs to this live target. Preserve explicit
    # external originals; only replace a configured live file with its backup.
    if configured==target.resolve() and native.is_file():
        parse(native);result['base_pck']=str(native.resolve())
        log('Оригінальна основа: VO_MEDIA.PC.PCK.gamedub_original.')
    parse(result['base_pck'])
    return result


def unique_output(output):
    output=Path(output)
    def occupied(p):
        return p.exists() or p.with_suffix('.BUILD_REPORT.json').exists() or (p.parent/(p.stem+'.data')).exists() or p.with_name(p.name+'.resonance-tmp').exists()
    if not occupied(output):return output
    for _ in range(100):
        candidate=output.with_name(output.stem+'_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]+output.suffix)
        if not occupied(candidate):return candidate
    raise ValueError('Не вдалося підібрати вільне ім’я інсталятора.')
