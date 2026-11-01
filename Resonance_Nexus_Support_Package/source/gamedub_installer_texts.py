"""Data-only text customization of the existing PS/C# installer templates."""
import hashlib
import json
import re

CYRILLIC = re.compile('[\u0400-\u04ff]')
GLOBAL_TOKENS = {'game', 'game_upper', 'tested_version'}
SPECIAL_PS = {
    'topSub': ('wizard.subtitle', 'Верхній підзаголовок', '{game_upper}  /  УКРАЇНСЬКА ЛОКАЛІЗАЦІЯ'),
    'gameLabel': ('wizard.game', 'Назва гри на першому кроці', '{game}'),
    'versionLabel': ('wizard.version', 'Перевірені збірки', 'Локалізацію перевірено на збірках гри: {tested_version}'),
}
LABELS = {
    'form': 'Заголовок вікна', 'topText': 'Верхня назва', 'heading': 'Головний заголовок',
    'pathLabel': 'Підпис поля папки гри', 'hint': 'Підказка вибору гри',
    'browse': 'Кнопка вибору папки', 'back': 'Кнопка «Назад»', 'next': 'Кнопка «Далі»',
    'restoreButton': 'Кнопка відновлення', 'closeButton': 'Кнопка закриття',
    'topMin': 'Кнопка згортання', 'topClose': 'Підпис кнопки закриття',
    'progressLabel': 'Початковий стан прогресу', 'resultLabel': 'Результат',
}
BUTTONS = {'Назад', 'Далі', 'Встановити', 'Огляд…', 'Закрити', 'Відновити до оригіналу', 'Оновити', '─'}

def ps_literals(source):
    """Small lexer: exclude comments and C# here-strings, keep exact spans."""
    i = 0
    while i < len(source):
        if source.startswith('<#', i):
            end = source.find('#>', i+2)
            if end < 0: raise ValueError('Незавершений коментар PowerShell.')
            i = end+2; continue
        if source[i] == '#':
            end = source.find('\n', i); i = len(source) if end < 0 else end+1; continue
        if source[i:i+2] in ("@'", '@"'):
            quote = source[i+1]
            end = re.search(r'(?m)^'+re.escape(quote+'@')+r'(?=\s|$)', source[i+2:])
            if end is None: raise ValueError('Незавершений here-string PowerShell.')
            i = i+2+end.end(); continue
        if source[i] not in "'\"":
            i += 1; continue
        start = i; quote = source[i]; i += 1
        while i < len(source):
            if quote == '"' and source[i] == '`': i += 2; continue
            if source[i] == quote:
                if quote == "'" and source[i:i+2] == "''": i += 2; continue
                i += 1; break
            i += 1
        else: raise ValueError('Незавершений рядок PowerShell.')
        yield start, i, quote, source[start+1:i-1]

def cs_literals(source):
    i = 0
    while i < len(source):
        if source.startswith('//', i):
            end = source.find('\n', i); i = len(source) if end < 0 else end+1; continue
        if source.startswith('/*', i):
            end = source.find('*/', i+2)
            if end < 0: raise ValueError('Незавершений коментар C#.')
            i = end+2; continue
        if source[i] != '"': i += 1; continue
        start = i; i += 1
        while i < len(source):
            if source[i] == '\\': i += 2; continue
            if source[i] == '"': i += 1; break
            i += 1
        else: raise ValueError('Незавершений рядок C#.')
        raw = source[start:i]
        # The existing bootstrap uses normal C# string literals only.
        yield start, i, json.loads(raw)

def ps_quote(value):
    return "'"+value.replace("'", "''")+"'"

def cs_quote(value):
    # JSON escaping is also valid for these C# string literals (no executable text).
    return json.dumps(value, ensure_ascii=True)

def key(prefix, value):
    return prefix+'.'+hashlib.sha256(value.encode('utf-8')).hexdigest()[:16]

def decode_ps(raw, quote):
    if quote == "'": return raw.replace("''", "'"), {}
    params = {}
    def variable(match):
        token = match.group()
        name = re.sub(r'[^a-zA-Z0-9_]', '_', token.removeprefix('$(').removesuffix(')').lstrip('$')).strip('_')
        name = {'manifest_game': 'game', 'state_phase': 'state_phase', '_': 'error', '': 'error'}.get(name, name)
        params[name] = token
        return '{'+name+'}'
    text = re.sub(r'\$\([^()]*\)|\$(?:[a-zA-Z_][\w]*(?:\.[\w]+)*)', variable, raw)
    text = re.sub(r'`(.)', lambda m: {'n':'\n','r':'\r','t':'\t','0':'\0'}.get(m[1],m[1]), text)
    return text, params

def _apply(source, edits):
    for a,b,text in sorted(edits, reverse=True): source = source[:a]+text+source[b:]
    return source

def scan_powershell(source):
    fields = []; edits = []; skips = []
    for variable, (field_key,label,default) in SPECIAL_PS.items():
        match = re.search(r'(?m)^\$'+variable+r'\.Text\s*=.*$', source)
        if match:
            skips.append(match.span())
            edits.append((*match.span(), '$'+variable+".Text = (InstallerUiText "+ps_quote(field_key)+' '+ps_quote(default)+')'))
            fields.append({'key':field_key, 'label':label, 'group':'Вікно', 'default':default,
                           'tokens':sorted(GLOBAL_TOKENS), 'multiline':False})
    seen = set()
    for a,b,quote,raw in ps_literals(source):
        if any(x <= a < y for x,y in skips): continue
        default, params = decode_ps(raw,quote)
        if not CYRILLIC.search(default) and default not in ('COLDVOICE','ColdVoice','─'): continue
        field_key = key('ps',raw+quote)
        nearby = source[max(0, source.rfind('\n',0,a)+1):a]
        variable = re.search(r'\$(\w+)\.(?:Text|AccessibleName)\s*=', nearby)
        var = variable[1] if variable else ''
        group = 'Кнопки' if default in BUTTONS or var in ('browse','back','next','restoreButton','closeButton','topMin','topClose') else ('Вікно' if var in LABELS else ('Кроки й описи' if re.match(r'\d\s*/\s*\d',default) else 'Повідомлення'))
        label = LABELS.get(var, default.splitlines()[0][:90])
        if var=='next' and default in ('Встановити','Оновити'):label='Кнопка «'+default+'»'
        if var=='resultLabel':label='Результат — '+default.splitlines()[0][:65]
        if field_key not in seen:
            fields.append({'key':field_key, 'label':label, 'group':group, 'default':default,
                           'tokens':sorted(GLOBAL_TOKENS | set(params)), 'multiline':group in ('Кроки й описи','Повідомлення') or var in ('hint','resultLabel','progressLabel')})
            seen.add(field_key)
        extra = ''
        if params:
            extra = ' @{'+ '; '.join(ps_quote(name)+' = [string]('+expression+')' for name,expression in params.items())+'}'
        edits.append((a,b,'(InstallerUiText '+ps_quote(field_key)+' '+source[a:b]+extra+')'))
    return _apply(source,edits), fields

def scan_bootstrap(source):
    fields = []; edits = []; seen = set()
    for a,b,default in cs_literals(source):
        if not CYRILLIC.search(default) and default not in ('COLDVOICE','ColdVoice'): continue
        field_key = key('cs',default)
        prefix = source[max(0,source.rfind('\n',0,a)+1):a]
        splash = any(x in prefix for x in ('Text =','title.Text','caption.Text'))
        label = ('Заголовок заставки' if 'title.Text' in prefix else 'Підпис заставки' if 'caption.Text' in prefix else 'Заголовок вікна заставки') if splash else default.splitlines()[0][:90]
        if field_key not in seen:
            fields.append({'key':field_key, 'label':label, 'group':'Заставка' if splash else 'Повідомлення заставки',
                           'default':default, 'tokens':[], 'multiline':not splash})
            seen.add(field_key)
        edits.append((a,b,'InstallerUiText('+cs_quote(field_key)+', '+source[a:b]+')'))
    return _apply(source,edits), fields

def catalog(ps_source, cs_source):
    return scan_bootstrap(cs_source)[1]+scan_powershell(ps_source)[1]

def validate(config, fields):
    if config is None: config = {}
    if not isinstance(config,dict): raise ValueError('Налаштування текстів мають бути об’єктом.')
    values = config.get('texts',{})
    if not isinstance(values,dict): raise ValueError('texts має бути об’єктом.')
    known = {f['key']:f for f in fields}; result = {}
    for name,value in values.items():
        # Unused old fields remain portable between template versions.
        if not isinstance(name,str) or not isinstance(value,str): raise ValueError('Назва й текст поля мають бути рядками.')
        if len(value)>6000 or any(ord(c)<32 and c not in '\r\n\t' for c in value):
            raise ValueError('Текст завеликий або містить керувальні символи: '+name)
        field = known.get(name)
        if field:
            if not field['multiline'] and '\n' in value: raise ValueError('Це однорядкове поле: '+field['label'])
            if field['group']=='Кнопки' and not value.strip(): raise ValueError('Кнопка повинна мати напис: '+field['label'])
            used = set(re.findall(r'\{([a-zA-Z_][a-zA-Z0-9_]*)\}', value))
            if used-set(field['tokens']): raise ValueError('Невідомий підставний параметр у полі «'+field['label']+'»: '+', '.join(sorted(used-set(field['tokens']))))
        result[name] = value.replace('\r\n','\n')
    return {'schema':1,'texts':result}

PS_FUNCTION = r'''
# COLDVOICE_INSTALLER_TEXTS_V1 -- plain data, never Invoke-Expression.
function InstallerUiText([string]$key, [string]$fallback, [hashtable]$values = @{}) {
    $text = $fallback
    if ($script:manifest.installer_ui -and $script:manifest.installer_ui.texts) {
        $property = $script:manifest.installer_ui.texts.PSObject.Properties[$key]
        if ($null -ne $property) { $text = [string]$property.Value }
    }
    $tokens = @{ 'game' = [string]$script:manifest.game; 'game_upper' = ([string]$script:manifest.game).ToUpperInvariant(); 'tested_version' = [string]$script:manifest.tested_version }
    foreach ($name in $values.Keys) { $tokens[$name] = [string]$values[$name] }
    # One pass: data containing another token never expands recursively.
    foreach ($match in @([regex]::Matches($text, '\{([a-zA-Z_][a-zA-Z0-9_]*)\}') | Sort-Object Index -Descending)) {
        $name = $match.Groups[1].Value
        if ($tokens.ContainsKey($name)) { $text = $text.Substring(0,$match.Index) + $tokens[$name] + $text.Substring($match.Index+$match.Length) }
    }
    return $text
}
'''

def render_powershell(source):
    if '# COLDVOICE_INSTALLER_TEXTS_V1' in source: raise ValueError('Шаблон уже має конструктор; потрібен початковий шаблон.')
    rendered,_ = scan_powershell(source)
    # Define before any safety/progress function can display text.
    match = re.search(r'(?m)^\$manifest\s*=.*$',rendered)
    if not match: raise ValueError('Не знайдено завантаження manifest у шаблоні.')
    rendered = rendered[:match.end()]+'\n$script:manifest = $manifest\n'+PS_FUNCTION+rendered[match.end():]
    return rendered

def render_archive_script(payload):
    """Accept the live builder's final str/bytes without discarding its edits."""
    if isinstance(payload,bytes):source=payload.decode('utf-8-sig')
    elif isinstance(payload,str):source=payload.lstrip('\ufeff')
    else:raise TypeError('Шаблон INSTALL.ps1 має бути текстом або UTF-8 байтами.')
    return render_powershell(source).encode('utf-8-sig')

def render_bootstrap(source, config):
    rendered, fields = scan_bootstrap(source)
    values = validate(config, fields)['texts']
    # Values are C# literals with escaping, never snippets of program code.
    rows = ',\n'.join('        { '+cs_quote(f['key'])+', '+cs_quote(values[f['key']])+' }' for f in fields if f['key'] in values)
    method = '''
    // COLDVOICE_INSTALLER_TEXTS_V1
    static readonly System.Collections.Generic.Dictionary<string,string> InstallerTexts =
        new System.Collections.Generic.Dictionary<string,string> {\n'''+rows+'''\n    };
    static string InstallerUiText(string key, string fallback) {
        string value;
        return InstallerTexts.TryGetValue(key, out value) ? value : fallback;
    }
'''
    anchor = '    const string Magic = "COLDVOICEZIPV01";'
    if rendered.count(anchor)!=1: raise ValueError('Не знайдено заголовок bootstrap C#.')
    return rendered.replace(anchor,anchor+method,1)

def preview_powershell(source):
    """The actual UI, with Install/Restore/CheckGame bypassed before file work."""
    rendered = render_powershell(source)
    for name in ('Install','Restore','CheckGame'):
        regex = r'(function '+name+r'\(\[string\]\$root\)\s*\{)'
        rendered,count = re.subn(regex, r'\1\n    if ($script:previewOnly) { return }',rendered,count=1)
        if count!=1: raise ValueError('Невідомий шаблон функції '+name+'; native preview вимкнено.')
    anchor = 'Test-Path -LiteralPath $path.Text -PathType Container'
    if rendered.count(anchor)!=1: raise ValueError('Невідомий вибір папки; native preview вимкнено.')
    rendered = rendered.replace(anchor,'($script:previewOnly -or ('+anchor+'))',1)
    # Set path to temporary preview package, never a user's game directory.
    rendered = rendered.replace('[Windows.Forms.Application]::Run($form)',
        "$path.Text = $base\n$form.Text = 'ПЕРЕГЛЯД — ' + $form.Text\n$heading.Text = 'ПЕРЕГЛЯД — ' + $heading.Text\n[Windows.Forms.Application]::Run($form)")
    return '$script:previewOnly = $true\n'+rendered
