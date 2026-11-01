"""Isolated APPROVED-WEM installer profile. No changes to the Build tab."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from resonance_pck import parse, sha, payload_hash, output_hash
from resonance_release_lifecycle import pristine_profile, unique_output
# COLDVOICE_RESONANCE_INSTALLER_LIFECYCLE_V3

HERE=Path(__file__).resolve().parent
MODE='resonance-approved-wem-v1'
NAME='Resonance: A Plague Tale Legacy'
EXTRA=('installer_mode','game_root','game_exe','base_pck','structure_path','project_dir','source_root','pck_target')

def selected(app):
    name=app.release_game_var.get()
    return next((p for p in getattr(app,'release_profiles',[]) if p['name']==name),{})

def default_profile():
    return {'name':NAME,'slug':'resonance','installer_mode':MODE,'game_marker':'SOUNDBANKS/VO_MEDIA.PC.PCK','process_name':'',
            'tested_version':'','files':[{'source':'UA/WEM','target':'SOUNDBANKS/VO_MEDIA.PC.PCK'}]}

def combined_ps(ps):
    anchor='[Windows.Forms.Application]::Run($form)'
    if ps.count(anchor)!=1:raise RuntimeError('Невідомий запуск майстра інсталятора.')
    return ps.replace(anchor,(HERE/'resonance_runtime.ps1').read_text(encoding='utf-8-sig')+'\n'+anchor,1)

def profile_extras(app,profile):
    old=selected(app)
    if old.get('installer_mode')!=MODE:return {}
    result={key:copy.deepcopy(old[key]) for key in EXTRA if key in old}
    result['installer_mode']=MODE
    result['source_root']=app.release_source_var.get().strip()
    return result

def choose_profile(app):
    """Independent picker: does not depend on the native combobox popdown."""
    if getattr(app,'busy',False):return
    window=tk.Toplevel(app)
    window.title('Вибрати гру — інсталятор')
    window.transient(app)
    window.resizable(False,False)
    frame=ttk.Frame(window,padding=16);frame.pack(fill='both',expand=True)
    ttk.Label(frame,text='Оберіть профіль інсталятора:').pack(anchor='w',pady=(0,10))
    def pick(name):
        window.destroy()
        app.release_game_var.set(name)
        app._release_select_profile()
    for profile in app.release_profiles:
        name=profile['name']
        ttk.Button(frame,text=name,command=lambda name=name:pick(name),width=48).pack(fill='x',pady=4)
    ttk.Button(frame,text='Закрити',command=window.destroy).pack(pady=(12,0))
    window.update_idletasks()
    x=app.winfo_rootx()+max(0,(app.winfo_width()-window.winfo_reqwidth())//2)
    y=app.winfo_rooty()+max(0,(app.winfo_height()-window.winfo_reqheight())//2)
    window.geometry('+%d+%d'%(x,y))
    window.lift();window.focus_set()

def install(App):
    if getattr(App,'_resonance_release_installed',False):return
    import gamedub_release_builder as builder
    old_load=builder.load_profiles
    def load(folder):
        profiles=old_load(folder)
        if not any(p.get('installer_mode')==MODE for p in profiles):
            new=default_profile()
            if any(p['name']==new['name'] or p['slug']==new['slug'] for p in profiles):
                new['name']+=' (UA WEM)';new['slug']='resonance-ua-wem'
            profiles=profiles+[new]
        return profiles
    builder.load_profiles=load
    old_select=App._release_select_profile;old_tab=App._build_release_installer_tab;old_build=App._release_build
    def select(app,*args):
        result=old_select(app,*args);p=selected(app)
        if p.get('installer_mode')==MODE:
            app.release_source_var.set(p.get('source_root') or str(app.project_dir or ''))
        for button in getattr(app,'_resonance_installer_buttons',[]):
            if p.get('installer_mode')==MODE:button.pack(side='left',padx=8)
            else:button.pack_forget()
        return result
    def tab(app):
        result=old_tab(app)
        def find(widget):
            for child in widget.winfo_children():
                if isinstance(child,ttk.Button) and str(child.cget('text'))=='Додати гру…':return child
                found=find(child)
                if found:return found
            return None
        anchor=find(app.tab_installer)
        if not anchor:raise RuntimeError('Не знайдено вибір профілю інсталятора.')
        ttk.Button(anchor.master,text='Вибрати гру…',command=lambda:choose_profile(app)).pack(side='left',padx=8)
        configure_button=ttk.Button(anchor.master,text='Налаштувати Resonance…',command=lambda:configure(app))
        nexus_button=ttk.Button(anchor.master,text='Зібрати ZIP для Nexus…',command=lambda:build(app,nexus=True))
        app._resonance_installer_buttons=[configure_button,nexus_button]
        if selected(app).get('installer_mode')==MODE:
            for button in app._resonance_installer_buttons:button.pack(side='left',padx=8)
        # Make the existing text constructor expose the Resonance-only messages.
        try:
            import gamedub_installer_constructor as constructor
            old_templates=constructor.templates
            def templates():
                ps,cs=old_templates()
                return (combined_ps(ps),cs) if selected(app).get('installer_mode')==MODE else (ps,cs)
            constructor.templates=templates
        except ImportError:pass
        return result
    def build(app,nexus=False):
        if selected(app).get('installer_mode')!=MODE:return old_build(app)
        if getattr(app,'busy',False):return
        profile=app._release_save_profile(refresh=False)
        if not profile:return
        try:
            validate_config(app,profile)
            replacements,counts=select_wems(app)
            app._validate_english_pack_targets(replacements)
        except Exception as exc:messagebox.showerror('Resonance',str(exc),parent=app);return
        extension='.zip' if nexus else '.exe'
        output=filedialog.asksaveasfilename(parent=app,defaultextension=extension,filetypes=[('Пакет Nexus','*.zip')] if nexus else [('Інсталятор','*.exe')],
            initialfile='ColdVoiceUA_Resonance_UA_Dubbing_Setup_'+datetime.now().strftime('%Y%m%d_%H%M%S')+extension)
        if not output:return
        # Snapshot rows/paths; authoring won't read a different selection mid-build.
        profile=copy.deepcopy(profile)
        def job():
            try:
                result=build_exe(profile,replacements,counts,output,app._log,nexus=nexus)
                app.ui_call(messagebox.showinfo,'Resonance',result)
            except Exception as exc:app.ui_call(messagebox.showerror,'Resonance',str(exc))
        app.run_bg('Resonance: інсталятор APPROVED UA WEM…',job)
    App._release_select_profile=select;App._build_release_installer_tab=tab;App._release_build=build
    App._resonance_release_installed=True

def configure(app):
    if getattr(app,'busy',False):return
    if not getattr(app,'db',None) or not app.project_dir:
        messagebox.showerror('Resonance','Відкрий проєкт Resonance перед налаштуванням.',parent=app);return
    p=selected(app)
    if p.get('installer_mode')!=MODE:
        messagebox.showinfo('Resonance','Спочатку вибери профіль Resonance у списку «Гра».',parent=app);return
    try:
        media=Path(app.db.get_meta('vo_media','')).resolve(strict=True)
        structure=Path(app.db.get_meta('vo_structure','')).resolve(strict=True)
        if media.name.upper()!='VO_MEDIA.PC.PCK' or structure.name.upper()!='VO_STRUCTURE.PC.PCK':raise RuntimeError('Це не проєкт VO_MEDIA/VO_STRUCTURE Resonance.')
        root_text=filedialog.askdirectory(parent=app,title='Коренева папка встановленої Resonance',initialdir=p.get('game_root') or str(media.parent.parent))
        if not root_text:return
        root=Path(root_text).resolve(strict=True);target=media.relative_to(root).as_posix();structure.relative_to(root)
        exe_text=filedialog.askopenfilename(parent=app,title='Основний EXE процесу Resonance (не launcher)',initialdir=str(root),filetypes=[('Game EXE','*.exe')])
        if not exe_text:return
        exe=Path(exe_text).resolve(strict=True);exe_relative=exe.relative_to(root).as_posix()
        original=media.with_name(media.name+'.gamedub_original')
        if not original.is_file():
            original_text=filedialog.askopenfilename(parent=app,title='Оригінальний VO_MEDIA.PC.PCK (до української озвучки)',initialdir=str(media.parent),filetypes=[('PCK/backup','*.PCK *.pck *.gamedub_original'),('Усі файли','*.*')])
            if not original_text:return
            original=Path(original_text).resolve(strict=True)
        # Only tiny header/table reads here; hashing is done in the build worker.
        parse(original)
        configured=copy.deepcopy(p)
        configured.update({'game_root':str(root),'game_exe':exe_relative,'base_pck':str(original),'structure_path':str(structure),
                           'project_dir':str(Path(app.project_dir).resolve()),'source_root':str(Path(app.project_dir).resolve()),'pck_target':target,
                           'game_marker':target,'process_name':exe.stem,'files':[{'source':'UA/WEM','target':target}]})
        from gamedub_installer_texts import catalog
        texts={}
        ps=(HERE/'gamedub_release_installer.ps1').read_text(encoding='utf-8-sig');cs=(HERE/'gamedub_release_bootstrap.cs').read_text(encoding='utf-8-sig')
        for field in catalog(combined_ps(ps),cs):
            if field['label']=='Головний заголовок':texts[field['key']]='ColdVoice — українська озвучка {game}'
        texts['wizard.subtitle']='{game_upper} / УКРАЇНСЬКА ОЗВУЧКА'
        texts.update((p.get('installer_ui') or {}).get('texts',{}))
        configured['installer_ui']={'schema':1,'texts':texts}
        profiles=[configured if x['name']==p['name'] else x for x in app.release_profiles]
        import gamedub_release_builder as builder
        builder.save_profiles(app._release_profiles_dir(),profiles)
        app._release_refresh_profiles(configured['name'])
        messagebox.showinfo('Resonance','Профіль налаштовано. Вкажи перевірену збірку гри й оформлення, потім «Зібрати інсталятор EXE».\n\nДжерело: APPROVED із готовими UA WEM. Повний PCK у пакет не включається.',parent=app)
    except Exception as exc:messagebox.showerror('Resonance',str(exc),parent=app)

def validate_config(app,profile):
    if not getattr(app,'db',None) or not app.project_dir:raise RuntimeError('Відкрий проєкт Resonance перед збіркою інсталятора.')
    for name in ('base_pck','structure_path','game_root','game_exe','pck_target','project_dir'):
        if not profile.get(name):raise RuntimeError('Спочатку натисни «Налаштувати Resonance…».')
    if Path(profile['project_dir']).resolve()!=Path(app.project_dir).resolve() or Path(profile['source_root']).resolve()!=Path(app.project_dir).resolve():
        raise RuntimeError('Відкрий проєкт Resonance, з якого налаштовано цей профіль, або налаштуй його заново.')
    active=Path(app.db.get_meta('vo_media','')).resolve(strict=True)
    expected=Path(profile['game_root']).resolve()/profile['pck_target']
    if active!=expected.resolve(strict=True):raise RuntimeError('Профіль не відповідає поточному VO_MEDIA проєкту.')
    if len(profile['files'])!=1 or profile['files'][0]['target']!=profile['pck_target']:
        raise RuntimeError('Профіль Resonance має одну ціль VO_MEDIA. Налаштуй його заново.')
    if not profile.get('tested_version','').strip():raise RuntimeError('Вкажи перевірену збірку гри.')
    if Path(profile['structure_path']).resolve()!=Path(app.db.get_meta('vo_structure','')).resolve(strict=True):raise RuntimeError('VO_STRUCTURE належить іншому проєкту.')

"""Replacement selector: explicit approval is the only editorial decision."""

def select_wems(app):
    # COLDVOICE_RESONANCE_APPROVED_ALL_V1_3
    with app.db.conn() as connection:
        rows = connection.execute(
            'SELECT * FROM lines WHERE approved=1 ORDER BY object_id'
        ).fetchall()
    reps = {}
    counts = {'rows_seen': len(rows), 'not_approved': 0, 'test': 0,
              'missing_wem': 0, 'nonverbal': 0, 'approved_objects': 0,
              'selection_policy': 'all-approved-no-text-filter'}
    missing = []
    invalid = []
    for raw in rows:
        row = dict(raw)
        object_id = int(row['object_id'])
        raw_path = str(row.get('ua_wem') or '').strip()
        path = Path(raw_path)
        if not raw_path or not path.is_file():
            missing.append(object_id)
            continue
        with path.open('rb') as stream:
            prefix = stream.read(12)
        if len(prefix) != 12 or prefix[:4] != b'RIFF' or prefix[8:] != b'WAVE':
            invalid.append(object_id)
            continue
        key = (1, int(app._pack_target_source_id(raw)))
        if key in reps and sha(reps[key][1]) != sha(path):
            raise RuntimeError('Різні APPROVED WEM для одного EN source ID: ' + str(key[1]))
        reps[key] = (row, path.resolve())
        counts['approved_objects'] += 1
    if missing or invalid:
        messages = ['Інсталятор не зібрано: усі APPROVED повинні мати готовий коректний WEM.']
        if missing:
            messages.append('Немає UA WEM, Object ID: ' + ', '.join(map(str, missing)))
        if invalid:
            messages.append('Некоректний UA WEM, Object ID: ' + ', '.join(map(str, invalid)))
        raise RuntimeError('\n'.join(messages))
    if not reps:
        raise RuntimeError('Немає APPROVED реплік для інсталятора.')
    counts['unique_source_targets'] = len(reps)
    return reps, counts

def package(profile,reps,counts,stage,log=print):
    from gamedub_installer_texts import catalog,validate,render_powershell
    import gamedub_release_builder as builder
    profile=pristine_profile(profile,log)
    original=Path(profile['base_pck']);info=parse(original);by_key={(e['language'],e['file_id']):e for e in info['entries']}
    payload=stage/'payload';payload.mkdir();replacement_rows=[];mapped={};counts=dict(counts);counts['identical_to_original']=0
    for key,(row,path) in sorted(reps.items()):
        if key not in by_key:raise RuntimeError('EN source ID відсутній у базовому PCK: '+str(key))
        digest=sha(path)
        if digest==payload_hash(original,by_key[key]):counts['identical_to_original']+=1
        rel='UA/'+str(key[1])+'.wem';dest=payload/rel;dest.parent.mkdir(exist_ok=True);shutil.copyfile(path,dest)
        if sha(dest)!=digest:raise RuntimeError('WEM змінився під час експорту.')
        mapped[key]=dest
        replacement_rows.append({'language_id':1,'source_id':key[1],'object_id':int(row['object_id']),'payload':rel,'size':dest.stat().st_size,'sha256':digest})
    if not mapped:raise RuntimeError('Усі вибрані WEM тотожні оригіналу; українського payload немає.')
    log('Resonance: SHA-256 оригінального PCK…');base_hash=sha(original)
    log('Resonance: розрахунок і перевірка нового layout без запису повного PCK…')
    target_hash,target_size=output_hash(original,info,mapped,progress=lambda n,total:log('PCK layout/hash: '+str(n)+' / '+str(total)))
    if sha(original)!=base_hash:raise RuntimeError('Оригінальний PCK змінився під час збірки.')
    ps=combined_ps((HERE/'gamedub_release_installer.ps1').read_text(encoding='utf-8-sig'))
    cs=(HERE/'gamedub_release_bootstrap.cs').read_text(encoding='utf-8-sig')
    manifest={'schema':1,'mode':MODE,'game':profile['name'],'slug':profile['slug'],'process':profile['process_name'],'game_exe':profile['game_exe'],
              'marker':profile['pck_target'],'tested_version':profile['tested_version'],'files':[{'target':profile['pck_target']}],
              'installer_ui':validate(profile.get('installer_ui'),catalog(ps,cs)),
              'pck':{'target':profile['pck_target'],'base_sha256':base_hash,'base_size':info['length'],'output_sha256':target_hash,'output_size':target_size,
                     'structure':Path(profile['structure_path']).resolve().relative_to(Path(profile['game_root']).resolve()).as_posix(),
                     'structure_sha256':sha(profile['structure_path']),'replacements':replacement_rows}}
    raw=json.dumps(manifest,ensure_ascii=False,indent=2).encode('utf-8')
    (payload/'manifest.json').write_bytes(raw);(payload/'INSTALL.ps1').write_text(render_powershell(ps),encoding='utf-8-sig')
    icon=Path(profile.get('installer_icon') or HERE/'gamedub_installer_default.ico')
    ico,png=builder._installer_icon_assets(icon);(payload/'INSTALLER.ico').write_bytes(ico);(payload/'INSTALLER.png').write_bytes(png)
    report={'mode':MODE,'counts':counts,'packed_wems':len(mapped),'ua_bytes':sum(r['size'] for r in replacement_rows),
            'base_pck_included':False,'original_payload_included':False,'output_size':target_size,'output_sha256':target_hash,
            'base_sha256':base_hash,'compatibility':'exact base PCK and VO_STRUCTURE SHA-256','nexus_approval_guaranteed':False}
    return manifest,report,payload,cs

def build_exe(profile,reps,counts,output,log=print,nexus=False):
    from gamedub_installer_texts import render_bootstrap,cs_quote
    if sys.platform!='win32':raise RuntimeError('EXE збирається у Windows.')
    requested_output=Path(output).resolve()
    output=unique_output(requested_output);output.parent.mkdir(parents=True,exist_ok=True)
    if output!=requested_output:log('Попередній реліз збережено. Новий файл: '+str(output))
    roots=[Path(profile['game_root']).resolve(),Path(profile['project_dir']).resolve()]
    if any(output==r or output.is_relative_to(r) for r in roots):raise RuntimeError('Збережи EXE поза папкою гри й проєкту.')
    if output.suffix.lower()!=('.zip' if nexus else '.exe'):raise RuntimeError('Неправильне розширення результату.')
    windows=Path(os.environ.get('SystemRoot',r'C:\Windows'))
    compiler=next((p for p in [windows/'Microsoft.NET/Framework64/v4.0.30319/csc.exe',windows/'Microsoft.NET/Framework/v4.0.30319/csc.exe'] if p.is_file()),None)
    if not compiler:raise RuntimeError('Не знайдено .NET Framework csc.')
    with tempfile.TemporaryDirectory(prefix='ColdVoiceResonanceBuild_') as tmp:
        stage=Path(tmp);manifest,report,payload,template=package(profile,reps,counts,stage,log)
        archive=stage/'ua.zip'
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_STORED,allowZip64=True) as z:
            for p in sorted(payload.rglob('*')):
                if p.is_file():z.write(p,p.relative_to(payload).as_posix())
        # Keep executable below 2 GiB. Larger UA packages use a loose data folder,
        # so a Nexus ZIP contains no nested payload archive.
        external=nexus or archive.stat().st_size>1900*1024*1024
        data_name=output.stem+'.data'
        if external:
            anchor='    static void ExtractPayload(string destination) {'
            if template.count(anchor)!=1:raise RuntimeError('Невідомий bootstrap для великого UA пакета.')
            template=template.replace(anchor,anchor+'\n        ResonancePckEngine.ExtractExternal(destination, '+cs_quote(data_name)+');\n        return;\n',1)
        # Engine contains technical diagnostic codes only, not original game data.
        source=stage/'ResonanceSetup.cs';source.write_text(render_bootstrap(template,manifest['installer_ui']),encoding='utf-8-sig')
        if profile.get('splash_image'):splash=Path(profile['splash_image'])
        else:
            # Neutral per-game fallback, rather than another game's artwork.
            from PIL import Image,ImageDraw,ImageFont
            splash=stage/'ResonanceSplash.png';image=Image.new('RGB',(900,410),(15,18,24));draw=ImageDraw.Draw(image)
            font_file=windows/'Fonts/segoeuib.ttf'
            font=ImageFont.truetype(str(font_file),48) if font_file.is_file() else ImageFont.load_default()
            small=ImageFont.truetype(str(font_file),22) if font_file.is_file() else ImageFont.load_default()
            draw.rectangle((60,80,65,300),fill=(83,165,213));draw.text((90,135),'RESONANCE',font=font,fill=(237,244,249))
            draw.text((95,210),'A PLAGUE TALE LEGACY',font=small,fill=(123,177,210));image.save(splash)
        exe=stage/'bootstrap.exe';command=[str(compiler),'/nologo','/target:winexe','/platform:x64','/out:'+str(exe),
            '/win32icon:'+str(payload/'INSTALLER.ico'),'/resource:'+str(splash)+',SplashImage',
            '/reference:System.Windows.Forms.dll','/reference:System.Drawing.dll','/reference:System.IO.Compression.dll',
            '/reference:System.IO.Compression.FileSystem.dll','/reference:System.Web.Extensions.dll']
        if external:
            for name in ('manifest.json','INSTALL.ps1','INSTALLER.ico','INSTALLER.png'):command.append('/resource:'+str(payload/name)+',Resonance.'+name)
        command.extend([str(source),str(HERE/'ResonancePckEngine.cs')])
        run=subprocess.run(command,capture_output=True,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
        if run.returncode:raise RuntimeError('C# compile: '+(run.stdout+run.stderr).decode('utf-8',errors='replace')[-2000:])
        for args in [('--verify-icon',str(payload/'INSTALLER.ico')),('--verify-host',)]:
            check=subprocess.run([str(exe),*args],capture_output=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
            if check.returncode:raise RuntimeError('Перевірка іконки/PowerShell host не пройшла.')
        temp=output.with_name(output.name+'.resonance-tmp')
        if temp.exists():raise RuntimeError('Існує незавершений EXE.')
        created_data_dir=None;committed=False
        try:
            if nexus:
                with zipfile.ZipFile(temp,'w',zipfile.ZIP_STORED,allowZip64=True) as z:
                    z.write(exe,output.stem+'.exe')
                    for wem in sorted((payload/'UA').glob('*.wem')):z.write(wem,data_name+'/UA/'+wem.name)
                    z.writestr('README_UA.txt','Розпакуйте ZIP повністю. Не переміщуйте EXE окремо від папки .data. Закрийте гру, запустіть EXE, виберіть кореневу папку Resonance. Для повернення оригіналу використайте цей інсталятор. Потрібна перевірена версія гри: '+profile['tested_version'])
                os.link(temp,output);committed=True;temp.unlink()
                report['external_data_folder']=data_name;report['nexus_archive']=True
                report_path=output.with_suffix('.BUILD_REPORT.json');report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
                return 'Пакет для завантаження на Nexus зібрано: '+str(output)+'\nUA WEM: '+str(report['packed_wems'])+'\nУ ZIP — EXE та українські WEM; оригінального PCK немає. Прийняття Nexus не гарантується.'
            with temp.open('xb') as dest,exe.open('rb') as code:
                shutil.copyfileobj(code,dest,4*1024*1024)
                if not external:
                    with archive.open('rb') as data:shutil.copyfileobj(data,dest,4*1024*1024)
                    dest.write(archive.stat().st_size.to_bytes(8,'little'));dest.write(b'COLDVOICEZIPV01')
            if external:
                data_dir=output.parent/data_name
                if data_dir.exists():raise RuntimeError('Папка даних уже існує; вибери нову назву EXE, щоб зберегти старий реліз.')
                data_dir.mkdir()
                created_data_dir=data_dir
                try:shutil.copytree(payload/'UA',data_dir/'UA')
                except Exception:shutil.rmtree(data_dir);raise
            os.link(temp,output);committed=True;temp.unlink()
        finally:
            temp.unlink(missing_ok=True)
            if created_data_dir is not None and not committed:shutil.rmtree(created_data_dir,ignore_errors=True)
        report['external_data_folder']=data_name if external else None
        report_path=output.with_suffix('.BUILD_REPORT.json');report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        if external:return 'EXE зібрано: '+str(output)+'\n\nПоруч створено '+data_name+'. Для поширення потрібні EXE і ця папка. Запакуй їх разом у ZIP.\nUA WEM: '+str(report['packed_wems'])
        return 'Інсталятор зібрано: '+str(output)+'\nUA WEM: '+str(report['packed_wems'])+'\nОригінальні репліки та повний PCK у EXE не включені.\nЗвіт: '+str(report_path)
