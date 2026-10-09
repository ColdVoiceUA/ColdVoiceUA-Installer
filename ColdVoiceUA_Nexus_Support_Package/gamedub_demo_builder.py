"""Selected-line Townfall demo export; leaves the project database unchanged."""
import copy
import hashlib
import json
from pathlib import Path


def wav_path(row, project):
    path = Path(str(row.get('ua_wav') or ''))
    if path.is_file():
        return path
    fallback = Path(project) / 'UA' / 'WAV' / (str(int(row['object_id'])) + '.wav')
    return fallback if fallback.is_file() else None


def restrict_ready(ready, object_ids):
    """Fail closed on missing takes, duplicate identities or a changed selection."""
    wanted = frozenset(int(x) for x in object_ids)
    if not wanted:
        raise ValueError('Виберіть хоча б одну репліку для Demo.')
    result = {key: row for key, row in ready.items() if int(row['object_id']) in wanted}
    found = {int(row['object_id']) for row in result.values()}
    if found != wanted:
        raise ValueError('Немає готового WAV або є повтор Voice ID для обраних реплік: ' +
                         ', '.join(map(str, sorted(wanted - found))))
    return result


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def export_demo(app, profile, output, chosen_rows, report, game_root):
    from gamedub_release_builder import build_exe
    from tkinter import messagebox
    proof = report.get('demo_selection') or {}
    wanted = {str(row.get('media_external_id') or row.get('dialoc_id')).strip().casefold()
              for row in chosen_rows}
    if not report.get('success') or set(proof.get('voice_ids', [])) != wanted:
        raise RuntimeError('Demo: збірка не підтвердила точний список реплік.')
    dialogue = report.get('dialogue_variable_fsb') or {}
    if dialogue.get('ua_q100') != len(wanted) or dialogue.get('english_exact') != 814 - len(wanted):
        raise RuntimeError('Demo: кількість UA / English fallback не відповідає вибору.')
    actual = (report.get('dialogue') or {}).get('samples_patched') or {}
    if {str(key).casefold() for key in actual} != wanted:
        raise RuntimeError('Demo: фактично замінені репліки не відповідають вибору.')
    cinematic = report.get('cinematic_authored_only_overlay_v80') or {}
    if not {str(x).casefold() for x in cinematic.get('assigned_voice_ids', [])}.issubset(wanted):
        raise RuntimeError('Demo: у cinematic-збірці знайдено репліки поза вибором.')
    # Verify the installed bank bytes against this specific successful build.
    install = report.get('install') or {}
    for name in ('Dialogue_JP', 'Cinematics_JP'):
        path = Path(game_root) / 'Townfall/Mods/ColdVoice' / (name + '.bank')
        expected = install.get(name + '_sha256')
        if not expected or not path.is_file() or sha(path) != expected:
            raise RuntimeError('Demo: банк не збігається з підтвердженою збіркою: ' + name)
    for row in chosen_rows:
        path = wav_path(row, app.project_dir)
        if path is None or sha(path) != row['_demo_wav_sha256']:
            raise RuntimeError('WAV змінився під час збірки Demo; EXE не створено.')
    demo_profile = copy.deepcopy(profile)
    demo_profile['name'] = profile['name'] + ' — Demo'
    for row in demo_profile['files']:
        target = row['target'].replace('\\', '/')
        for name in ('Dialogue_JP.bank', 'Cinematics_JP.bank'):
            if target in ('Townfall/Mods/ColdVoice/' + name, 'Townfall/Content/FMOD/Banks/Desktop/' + name):
                row['source'] = 'Townfall/Mods/ColdVoice/' + name
    path, manifest = build_exe(demo_profile, game_root, output)
    app.ui_call(messagebox.showinfo, 'ColdVoice Demo',
                f'Demo EXE зібрано:\n{path}\n\n'
                f'Українських реплік: {len(wanted)}\n'
                f'Англійський fallback: {814 - len(wanted)}\n\n'
                'Для повної версії знову запустіть звичайну збірку Townfall.')


def open_demo(app):
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog
    from datetime import datetime
    if app.busy:
        messagebox.showinfo('ColdVoice Demo', 'Дочекайтеся завершення поточної операції.')
        return
    if not app.project_dir or not app.db:
        messagebox.showerror('ColdVoice Demo', 'Спочатку відкрийте Townfall-проєкт.')
        return
    if getattr(app, 'project_adapter', '') != 'townfall':
        messagebox.showerror('ColdVoice Demo', 'Відкрийте проєкт із Townfall adapter.')
        return
    if not app._ue5_is_current_project():
        messagebox.showerror('ColdVoice Demo', 'Відкрийте Townfall-проєкт саме для вибраної папки гри.')
        return
    if not app.ue5_game_root_var.get().strip():
        messagebox.showerror('ColdVoice Demo', 'Спочатку виберіть папку гри у вкладці UE5.')
        return
    if app.release_slug_var.get().strip() != 'townfall':
        messagebox.showerror('ColdVoice Demo', 'Виберіть профіль Silent Hill: Townfall.')
        return
    try:
        with app.db.conn() as conn:
            rows = [dict(row) for row in conn.execute(
                'SELECT object_id,media_external_id,dialoc_id,dialoc_tag,speaker,en_text,ua_text,ua_wav '
                'FROM lines ORDER BY object_id').fetchall()]
        rows = [row for row in rows if str(row.get('media_external_id') or row.get('dialoc_id') or '').strip()
                and wav_path(row, app.project_dir) is not None]
        if not rows:
            raise ValueError('У проєкті немає готових українських WAV.')
    except Exception as exc:
        messagebox.showerror('ColdVoice Demo', str(exc))
        return
    selection_path = Path(app.project_dir) / 'coldvoice_demo_selection.json'
    initial_project = Path(app.project_dir).resolve()
    initial_game = Path(app.ue5_game_root_var.get().strip()).resolve()
    try:
        saved = json.loads(selection_path.read_text(encoding='utf-8'))
        selected = set(map(int, saved.get('object_ids', [])))
    except (OSError, ValueError, TypeError):
        selected = set()
    selected &= {int(row['object_id']) for row in rows}
    window = tk.Toplevel(app)
    window.title('ColdVoice — вибір реплік Demo')
    window.geometry('1000x650')
    window.minsize(750, 460)
    window.transient(app)
    frame = ttk.Frame(window, padding=12)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='Позначте готові репліки для Demo. Решта голосів залишиться англійською.').pack(anchor='w')
    ttk.Label(frame, text='Збірка оновить банки у вибраній локальній грі та створить окремий Demo EXE.').pack(anchor='w', pady=(0, 8))
    query = tk.StringVar()
    entry = ttk.Entry(frame, textvariable=query)
    entry.pack(fill='x', pady=4)
    table_frame = ttk.Frame(frame)
    table_frame.pack(fill='both', expand=True)
    tree = ttk.Treeview(table_frame, columns=('picked', 'id', 'speaker', 'text'), show='headings', selectmode='extended')
    for column, label, width in [('picked', 'Demo', 55), ('id', 'Voice ID', 85), ('speaker', 'Персонаж', 150), ('text', 'Репліка', 620)]:
        tree.heading(column, text=label)
        tree.column(column, width=width, stretch=column == 'text')
    scrollbar = ttk.Scrollbar(table_frame, orient='vertical', command=tree.yview)
    tree.configure(yscrollcommand=scrollbar.set)
    tree.pack(side='left', fill='both', expand=True)
    scrollbar.pack(side='right', fill='y')
    count = tk.StringVar()

    def redraw(*_):
        tree.delete(*tree.get_children())
        search = query.get().strip().casefold()
        for row in rows:
            voice = str(row.get('media_external_id') or row.get('dialoc_id'))
            text = str(row.get('ua_text') or row.get('en_text') or '')
            if search and search not in (voice + ' ' + str(row.get('speaker') or '') + ' ' + text + ' ' + str(row.get('dialoc_tag') or '')).casefold():
                continue
            oid = int(row['object_id'])
            tree.insert('', 'end', iid=str(oid), values=('✓' if oid in selected else '', voice, row.get('speaker') or '', text))
        count.set(f'Обрано: {len(selected)} · готових WAV: {len(rows)}')

    def mark(value):
        for item in tree.selection():
            if value:
                selected.add(int(item))
            else:
                selected.discard(int(item))
        redraw()

    def toggle(event):
        item = tree.identify_row(event.y)
        if item:
            oid = int(item)
            selected.discard(oid) if oid in selected else selected.add(oid)
            redraw()

    def start():
        if app.busy:
            messagebox.showinfo('ColdVoice Demo', 'Зараз виконується інша операція.', parent=window)
            return
        if not selected:
            messagebox.showerror('ColdVoice Demo', 'Позначте хоча б одну репліку.', parent=window)
            return
        try:
            if Path(app.project_dir).resolve() != initial_project or Path(app.ue5_game_root_var.get().strip()).resolve() != initial_game:
                raise ValueError('Проєкт або папка гри змінилися. Відкрийте вибір Demo заново.')
            profile = app._release_save_profile(refresh=False)
            if not profile:
                raise ValueError('Не вдалося зберегти профіль інсталятора.')
            if not str(profile.get('tested_version') or '').strip():
                raise ValueError('Вкажіть перевірену збірку гри у профілі інсталятора.')
            chosen = [dict(row) for row in rows if int(row['object_id']) in selected]
            for row in chosen:
                path = wav_path(row, app.project_dir)
                if path is None:
                    raise ValueError('Обраний WAV більше не існує.')
                row['_demo_wav_sha256'] = sha(path)
            output = filedialog.asksaveasfilename(parent=window, defaultextension='.exe',
                filetypes=[('Windows installer', '*.exe')],
                initialfile='ColdVoice_Townfall_Demo_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '.exe')
            if not output:
                return
            if Path(output).resolve().is_relative_to(initial_game):
                raise ValueError('Збережіть Demo EXE поза папкою гри.')
            payload = {'schema': 1, 'object_ids': sorted(selected)}
            tmp = selection_path.with_suffix('.tmp')
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
            tmp.replace(selection_path)
            ids = frozenset(selected)
            window.destroy()
            app.ue5_townfall_install_jp_slot_ua_final_v57(
                demo_object_ids=ids,
                demo_on_success=lambda report, root: export_demo(app, profile, output, chosen, report, root))
        except Exception as exc:
            messagebox.showerror('ColdVoice Demo', str(exc))

    query.trace_add('write', redraw)
    tree.bind('<Double-1>', toggle)
    actions = ttk.Frame(frame)
    actions.pack(fill='x', pady=10)
    ttk.Button(actions, text='Додати виділені', command=lambda: mark(True)).pack(side='left')
    ttk.Button(actions, text='Прибрати виділені', command=lambda: mark(False)).pack(side='left', padx=6)
    ttk.Button(actions, text='Очистити вибір', command=lambda: (selected.clear(), redraw())).pack(side='left')
    ttk.Button(actions, text='Зібрати Demo EXE', command=start).pack(side='right')
    ttk.Label(frame, textvariable=count).pack(anchor='w')
    redraw()
    window.update_idletasks()
    window.geometry(f'+{max(0, app.winfo_rootx() + (app.winfo_width() - window.winfo_width()) // 2)}+'
                    f'{max(0, app.winfo_rooty() + (app.winfo_height() - window.winfo_height()) // 2)}')
    entry.focus_set()
