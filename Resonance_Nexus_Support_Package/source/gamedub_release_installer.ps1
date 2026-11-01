# GameDub standalone Windows PowerShell 5.1 installer. Lives beside manifest.json and Payload.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Windows.Forms;
public sealed class ColdVoiceShadowForm : Form {
    protected override CreateParams CreateParams {
        get { CreateParams cp = base.CreateParams; cp.ClassStyle |= 0x00020000; cp.ExStyle |= 0x00040000; return cp; }
    }
}
public static class ColdVoiceWindowApi {
    [DllImport("user32.dll")] public static extern bool ReleaseCapture();
    [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr hWnd, int msg, int wParam, int lParam);
}

// Native Explorer folder picker; no legacy SHBrowseForFolder tree.
public static class ColdVoiceFolderPicker {
    [ComImport, Guid("D57C7288-D4AD-4768-BE02-9D969532D960"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IFileOpenDialog {
        [PreserveSig] int Show(IntPtr owner);
        void SetFileTypes(uint count, IntPtr filters);
        void SetFileTypeIndex(uint index);
        void GetFileTypeIndex(out uint index);
        void Advise(IntPtr events, out uint cookie);
        void Unadvise(uint cookie);
        void SetOptions(uint options);
        void GetOptions(out uint options);
        void SetDefaultFolder(IShellItem folder);
        void SetFolder(IShellItem folder);
        void GetFolder(out IShellItem folder);
        void GetCurrentSelection(out IShellItem item);
        void SetFileName([MarshalAs(UnmanagedType.LPWStr)] string name);
        void GetFileName(out IntPtr name);
        void SetTitle([MarshalAs(UnmanagedType.LPWStr)] string title);
        void SetOkButtonLabel([MarshalAs(UnmanagedType.LPWStr)] string label);
        void SetFileNameLabel([MarshalAs(UnmanagedType.LPWStr)] string label);
        void GetResult(out IShellItem item);
        void AddPlace(IShellItem item, uint alignment);
        void SetDefaultExtension([MarshalAs(UnmanagedType.LPWStr)] string extension);
        void Close(int result);
        void SetClientGuid(ref Guid guid);
        void ClearClientData();
        void SetFilter(IntPtr filter);
        void GetResults(out IntPtr items);
        void GetSelectedItems(out IntPtr items);
    }
    [ComImport, Guid("43826D1E-E718-42EE-BC55-A1E261C37BFE"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IShellItem {
        void BindToHandler(IntPtr context, ref Guid handler, ref Guid iid, out IntPtr value);
        void GetParent(out IShellItem parent);
        void GetDisplayName(uint kind, out IntPtr name);
        void GetAttributes(uint mask, out uint attributes);
        void Compare(IShellItem item, uint hint, out int order);
    }
    [DllImport("shell32.dll", CharSet = CharSet.Unicode, PreserveSig = true)]
    static extern int SHCreateItemFromParsingName(string name, IntPtr context, ref Guid iid,
        [MarshalAs(UnmanagedType.Interface)] out IShellItem item);
    public static string Select(IntPtr owner, string initialFolder) {
        if (System.Threading.Thread.CurrentThread.GetApartmentState() != System.Threading.ApartmentState.STA)
            throw new InvalidOperationException("Folder picker requires an STA thread.");
        object instance = null;
        IShellItem initial = null, selected = null;
        IntPtr text = IntPtr.Zero;
        try {
            instance = Activator.CreateInstance(Type.GetTypeFromCLSID(new Guid("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7")));
            IFileOpenDialog dialog = (IFileOpenDialog)instance;
            uint options;
            dialog.GetOptions(out options);
            // PICKFOLDERS | FORCEFILESYSTEM | PATHMUSTEXIST | NOCHANGEDIR
            dialog.SetOptions(options | 0x20u | 0x40u | 0x800u | 0x8u);
            dialog.SetTitle("Оберіть кореневу папку гри");
            dialog.SetOkButtonLabel("Обрати папку");
            if (!String.IsNullOrWhiteSpace(initialFolder) && System.IO.Directory.Exists(initialFolder)) {
                Guid iid = new Guid("43826D1E-E718-42EE-BC55-A1E261C37BFE");
                if (SHCreateItemFromParsingName(initialFolder, IntPtr.Zero, ref iid, out initial) >= 0)
                    dialog.SetFolder(initial);
            }
            int result = dialog.Show(owner);
            if (result == unchecked((int)0x800704C7)) return null;
            if (result < 0) Marshal.ThrowExceptionForHR(result);
            dialog.GetResult(out selected);
            selected.GetDisplayName(0x80058000u, out text); // SIGDN_FILESYSPATH
            string folder = Marshal.PtrToStringUni(text);
            if (String.IsNullOrWhiteSpace(folder) || !System.IO.Directory.Exists(folder))
                throw new System.IO.DirectoryNotFoundException("Selected folder is unavailable.");
            return folder;
        } finally {
            if (text != IntPtr.Zero) Marshal.FreeCoTaskMem(text);
            if (selected != null) Marshal.ReleaseComObject(selected);
            if (initial != null) Marshal.ReleaseComObject(initial);
            if (instance != null) Marshal.ReleaseComObject(instance);
        }
    }
}
'@ -ReferencedAssemblies @('System.Windows.Forms.dll','System.Drawing.dll')
$base = $(if ($env:COLDVOICE_INSTALL_ROOT) { $env:COLDVOICE_INSTALL_ROOT } else { $PSScriptRoot })
$manifest = Get-Content -LiteralPath (Join-Path $base 'manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
function SafePath([string]$value) {
    $v = $value.Replace('/', '\')
    if ([IO.Path]::IsPathRooted($v) -or $v -match '(^|\\)(\.|\.\.)(\\|$)|:|\\\\' -or [string]::IsNullOrWhiteSpace($v)) { throw "Небезпечний шлях: $value" }
    return $v
}
function Hash([string]$file) { return (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() }
function AtomicCopy([string]$src, [string]$dest, [string]$expected) {
    $parent = Split-Path -Parent $dest
    [IO.Directory]::CreateDirectory($parent) | Out-Null
    $tmp = "$dest.coldvoice-tmp"
    if (Test-Path -LiteralPath $tmp) { throw "Незавершений тимчасовий файл: $tmp" }
    try {
        Copy-Item -LiteralPath $src -Destination $tmp -ErrorAction Stop
        if ((Hash $tmp) -ne $expected) { throw "Контрольна сума не збіглася: $dest" }
        Move-Item -LiteralPath $tmp -Destination $dest -Force -ErrorAction Stop
        if ((Hash $dest) -ne $expected) { throw "Перевірка після запису не пройшла: $dest" }
    } finally { if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force } }
}
function StateSave([string]$statePath, $state) {
    $tmp = "$statePath.tmp"
    $state | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $tmp -Encoding UTF8
    Move-Item -LiteralPath $tmp -Destination $statePath -Force
}
function CheckGame([string]$root) {
    if (-not (Test-Path -LiteralPath (Join-Path $root (SafePath $manifest.marker)) -PathType Leaf)) { throw "Це не $($manifest.game): відсутній маркер гри." }
    $proc = [string]$manifest.process
    if ($proc -and @(Get-Process -Name $proc -ErrorAction SilentlyContinue).Count -gt 0) { throw 'Повністю закрийте гру перед установленням або відновленням.' }
}
function RestoreRows([string]$root, [string]$stateDir, $state, [bool]$checkInstalled) {
    $restoreRows = $(if ($state -is [array]) { $state } else { $state.files })
    foreach ($row in $restoreRows) {
        UpdateProgress ('Відновлення ' + [string]$row.target) -1
        $dest = Join-Path $root (SafePath ([string]$row.target))
        if ($checkInstalled -and (Test-Path -LiteralPath $dest) -and (Hash $dest) -ne [string]$row.installed) {
            throw "Файл змінився після встановлення: $dest. Відновлення зупинено."
        }
        if ($row.existed) {
            $backup = Join-Path $stateDir (SafePath ([string]$row.backup))
            if (-not (Test-Path -LiteralPath $backup) -or (Hash $backup) -ne [string]$row.original) { throw "Пошкоджений backup: $backup" }
            AtomicCopy $backup $dest ([string]$row.original)
        } elseif (Test-Path -LiteralPath $dest -PathType Leaf) { Remove-Item -LiteralPath $dest -Force }
        elseif (Test-Path -LiteralPath $dest) { throw "Шлях зайнятий папкою: $dest" }
    }
}
function FindOriginal([string]$root, [string]$target, [string]$expected) {
    if ($expected -notmatch '^[0-9a-f]{64}$') { throw "Немає підтвердженої SHA оригіналу: $target" }
    $dest = Join-Path $root (SafePath $target)
    $parent = Split-Path -Parent $dest; $name = Split-Path -Leaf $dest
    $candidates = @(Get-ChildItem -LiteralPath $parent -Filter ($name + '*') -File -ErrorAction SilentlyContinue)
    if ($name -eq 'pakchunk1-Windows.pak') {
        $alternate = Join-Path $parent 'pakchunk1-Windows.ORIGINAL_BACKUP.pak'
        if (Test-Path -LiteralPath $alternate -PathType Leaf) { $candidates += Get-Item -LiteralPath $alternate }
    }
    foreach ($candidate in $candidates) {
        if ((Hash $candidate.FullName) -eq $expected) { return $candidate.FullName }
    }
    throw "Не знайдено підтверджений оригінал $target. Потрібен справжній backup гри; файли моду не будуть збережені як оригінали."
}
function PrepareOriginalRows([string]$root, $rows) {
    $expected = @{}
    foreach ($entry in $manifest.originals) { $expected[(SafePath ([string]$entry.target)).ToLowerInvariant()] = [string]$entry.sha256 }
    foreach ($entry in $manifest.baseline) { $expected[(SafePath ([string]$entry.target)).ToLowerInvariant()] = [string]$entry.sha256 }
    foreach ($row in $rows) {
        $rel = SafePath ([string]$row.target); $key = $rel.ToLowerInvariant()
        if ($key.StartsWith('townfall\mods\coldvoice\') -or $key.StartsWith('townfall\content\paks\~mods\') -or $key.StartsWith('townfall\content\paks\pakchunk9999-gamedubua-windows_p.')) {
            # These are ColdVoice additions; clean game never had them.
            $row.existed = $false; $row.original = ''
        } elseif ($expected.ContainsKey($key)) {
            $source = FindOriginal $root ([string]$row.target) $expected[$key]
            $row.existed = $true; $row.original = $expected[$key]
            $row | Add-Member -NotePropertyName original_source -NotePropertyValue $source
        } else { throw "Немає підтвердженого оригіналу для оновлення: $rel" }
    }
}

function CreatedDirectories([string]$root, $rows) {
    $rootFull = [IO.Path]::GetFullPath($root).TrimEnd('\')
    $seen = @{}
    foreach ($row in $rows) {
        $folder = Split-Path -Parent (Join-Path $root (SafePath ([string]$row.target)))
        while ($folder -and [IO.Path]::GetFullPath($folder).TrimEnd('\') -ne $rootFull) {
            if (-not (Test-Path -LiteralPath $folder)) {
                $relative = [IO.Path]::GetFullPath($folder).Substring($rootFull.Length).TrimStart('\')
                $seen[$relative] = $true
            }
            $folder = Split-Path -Parent $folder
        }
    }
    foreach ($key in $seen.Keys) { Write-Output ([string]$key) }
}
function CleanupDirectories([string]$root, $directories, [bool]$legacy) {
    $candidates = @($directories)
    if ($legacy -and [string]$manifest.slug -eq 'townfall') {
        $candidates += @('Townfall\Mods\ColdVoice', 'Townfall\Mods', 'Townfall\Content\Paks\~mods')
    }
    $candidates += '.ColdVoiceInstaller'
    foreach ($rel in @($candidates | Where-Object { $_ } | Select-Object -Unique | Sort-Object { ([string]$_).Length } -Descending)) {
        $folder = Join-Path $root (SafePath ([string]$rel))
        if ((Test-Path -LiteralPath $folder -PathType Container) -and @(Get-ChildItem -LiteralPath $folder -Force -ErrorAction Stop).Count -eq 0) {
            Remove-Item -LiteralPath $folder -Force -ErrorAction Stop
        }
    }
}

function ExistingColdVoice([string]$root) {
    if ([string]$manifest.slug -ne 'townfall') { return $false }
    # A subsequent GameDub build can legitimately change native banks independently.
    # Recognize ColdVoice additions; original recovery is verified separately by SHA.
    foreach ($rel in $manifest.require_absent) {
        if (Test-Path -LiteralPath (Join-Path $root (SafePath ([string]$rel))) -PathType Leaf) { return $true }
    }
    return $false
}
function RestoreScope($state) { return 'original' }
function RecoverUpdate([string]$root, [string]$stateDir, [string]$statePath, $state) {
    $transaction = Join-Path $stateDir (SafePath ([string]$state.update_dir))
    $journalPath = Join-Path $transaction 'transaction.json'
    if (-not (Test-Path -LiteralPath $journalPath -PathType Leaf)) { throw "Бракує журналу оновлення: $journalPath" }
    $journal = Get-Content -LiteralPath $journalPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($journal.previous_state.game -ne $manifest.game -or $journal.previous_state.phase -ne 'installed') { throw 'Некоректний журнал попередньої установки.' }
    # Verify every rollback copy before changing any destination.
    foreach ($row in $journal.rollback_rows) {
        if ($row.existed) {
            $saved = Join-Path $transaction (SafePath ([string]$row.backup))
            if (-not (Test-Path -LiteralPath $saved -PathType Leaf) -or (Hash $saved) -ne [string]$row.original) { throw "Пошкоджений backup оновлення: $saved" }
        }
    }
    RestoreRows $root $transaction $journal.rollback_rows $false
    StateSave $statePath $journal.previous_state
    Remove-Item -LiteralPath $transaction -Recurse -Force -ErrorAction SilentlyContinue
    CleanupDirectories $root $journal.created_dirs $false
    return $journal.previous_state
}
function UpdateInstallation([string]$root, [string]$stateDir, [string]$statePath, $previous) {
    if ($previous.game -ne $manifest.game) { throw 'Стан належить іншій грі.' }
    if ($previous.phase -eq 'updating') { $previous = RecoverUpdate $root $stateDir $statePath $previous }
    if ($previous.phase -ne 'installed') { throw 'Попередня операція перервана. Спочатку виконайте відновлення.' }
    $oldByTarget = @{}
    foreach ($row in $previous.files) {
        $key = (SafePath ([string]$row.target)).ToLowerInvariant()
        if ($oldByTarget.ContainsKey($key)) { throw 'Повторення цілі у стані установки.' }
        $oldByTarget[$key] = $row
        if ($row.existed) {
            $saved = Join-Path $stateDir (SafePath ([string]$row.backup))
            if (-not (Test-Path -LiteralPath $saved -PathType Leaf) -or (Hash $saved) -ne [string]$row.original) { throw "Пошкоджений первинний backup: $saved" }
        }
    }
    $nextRows = @(); $seen = @{}; $allTargets = @{}
    foreach ($row in $previous.files) { $allTargets[(SafePath ([string]$row.target)).ToLowerInvariant()] = [string]$row.target }
    foreach ($file in $manifest.files) {
        $rel = SafePath ([string]$file.target); $key = $rel.ToLowerInvariant()
        if ($seen.ContainsKey($key)) { throw "Повторення цілі: $rel" }
        $seen[$key] = $true; $allTargets[$key] = [string]$file.target
        $payload = Join-Path $base (SafePath ([string]$file.payload))
        if (-not (Test-Path -LiteralPath $payload -PathType Leaf) -or (Hash $payload) -ne [string]$file.sha256) { throw "Відсутній або змінений payload: $payload" }
        $dest = Join-Path $root $rel
        if ((Test-Path -LiteralPath $dest) -and -not (Test-Path -LiteralPath $dest -PathType Leaf)) { throw "Шлях зайнятий папкою: $dest" }
        $old = $oldByTarget[$key]
        if ($old) {
            # Retain the first installation's originals, never the old mod as originals.
            $nextRows += [pscustomobject]@{ target = [string]$file.target; payload = [string]$file.payload; installed = [string]$file.sha256; existed = [bool]$old.existed; original = [string]$old.original; backup = [string]$old.backup }
        } else {
            $exists = Test-Path -LiteralPath $dest -PathType Leaf
            $newRow = [pscustomobject]@{ target = [string]$file.target; payload = [string]$file.payload; installed = [string]$file.sha256; existed = $exists; original = $(if ($exists) { Hash $dest } else { '' }); backup = 'Original' + $rel }
            if ([string]$manifest.slug -eq 'townfall') { PrepareOriginalRows $root @($newRow) }
            $nextRows += $newRow
        }
    }
    $newDirectories = @(CreatedDirectories $root $nextRows)
    $createdDirectories = @($previous.created_dirs) + $newDirectories
    $legacyCleanup = [bool]($previous.cleanup_legacy -or $previous.PSObject.Properties.Name -notcontains 'created_dirs')
    $transactionName = 'Update_' + [Guid]::NewGuid().ToString('N')
    $transaction = Join-Path $stateDir $transactionName
    [IO.Directory]::CreateDirectory($transaction) | Out-Null
    $rollbackRows = @()
    try {
        foreach ($entry in $allTargets.GetEnumerator()) {
            $rel = SafePath ([string]$entry.Value); $dest = Join-Path $root $rel
            if ((Test-Path -LiteralPath $dest) -and -not (Test-Path -LiteralPath $dest -PathType Leaf)) { throw "Шлях зайнятий папкою: $dest" }
            $exists = Test-Path -LiteralPath $dest -PathType Leaf
            $row = [pscustomobject]@{ target = [string]$entry.Value; existed = $exists; original = $(if ($exists) { Hash $dest } else { '' }); backup = 'Previous\' + $rel }
            if ($exists) {
                $saved = Join-Path $transaction $row.backup
                [IO.Directory]::CreateDirectory((Split-Path -Parent $saved)) | Out-Null
                Copy-Item -LiteralPath $dest -Destination $saved -ErrorAction Stop
                if ((Hash $saved) -ne $row.original) { throw "Backup оновлення не пройшов перевірку: $dest" }
            }
            $rollbackRows += $row
        }
        foreach ($row in $nextRows) {
            $key = (SafePath ([string]$row.target)).ToLowerInvariant()
            if (-not $oldByTarget.ContainsKey($key) -and $row.existed) {
                $saved = Join-Path $stateDir (SafePath ([string]$row.backup))
                [IO.Directory]::CreateDirectory((Split-Path -Parent $saved)) | Out-Null
                $originalSource = $(if ($row.original_source) { [string]$row.original_source } else { Join-Path $root (SafePath ([string]$row.target)) })
                AtomicCopy $originalSource $saved ([string]$row.original)
            }
        }
        $journal = [pscustomobject]@{ previous_state = $previous; rollback_rows = $rollbackRows; created_dirs = $newDirectories }
        StateSave (Join-Path $transaction 'transaction.json') $journal
    } catch {
        Remove-Item -LiteralPath $transaction -Recurse -Force -ErrorAction SilentlyContinue
        throw
    }
    $pending = [pscustomobject]@{ schema = 1; game = [string]$manifest.game; phase = 'updating'; files = $previous.files; restore_scope = (RestoreScope $previous); update_dir = $transactionName }
    StateSave $statePath $pending
    try {
        $index = 0
        foreach ($row in $nextRows) {
            $index++
            UpdateProgress ('Оновлення ' + [string]$row.target) ([int](25 + 65 * $index / $nextRows.Count))
            AtomicCopy (Join-Path $base (SafePath ([string]$row.payload))) (Join-Path $root (SafePath ([string]$row.target))) ([string]$row.installed)
        }
        # Targets removed from the new release return to their first-install state.
        foreach ($row in $previous.files) {
            if (-not $seen.ContainsKey((SafePath ([string]$row.target)).ToLowerInvariant())) { RestoreRows $root $stateDir @($row) $false }
        }
        $nextState = [pscustomobject]@{ schema = 1; game = [string]$manifest.game; phase = 'installed'; files = $nextRows; restore_scope = (RestoreScope $previous); created_dirs = $createdDirectories; cleanup_legacy = $legacyCleanup }
        StateSave $statePath $nextState
    } catch {
        $failure = $_
        try { $null = RecoverUpdate $root $stateDir $statePath $pending }
        catch { throw "Помилка оновлення: $failure`nАвтовідкат не завершився: $_`nBackup збережено: $transaction" }
        throw "Оновлення не завершено. Попередню версію відновлено: $failure"
    }
    Remove-Item -LiteralPath $transaction -Recurse -Force -ErrorAction SilentlyContinue
    UpdateProgress 'Нову версію встановлено; первинні резервні копії збережено.' 100
}

function Install([string]$root) {
    UpdateProgress 'Перевірка гри та вмісту пакета…' 5
    CheckGame $root
    $slug = SafePath ([string]$manifest.slug)
    $stateDir = Join-Path $root ('.ColdVoiceInstaller\' + $slug)
    $statePath = Join-Path $stateDir 'state.json'
    if (Test-Path -LiteralPath $statePath) {
        $previous = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
        UpdateInstallation $root $stateDir $statePath $previous
        return
    }
    $adopting = ExistingColdVoice $root
    if (Test-Path -LiteralPath $stateDir) { throw "Існує незавершений стан інсталятора: $stateDir" }
    $rows = @(); $seen = @{}
    foreach ($file in @($manifest.files)) {
        UpdateProgress ('Перевірка ' + [string]$file.target) 8
        $rel = SafePath ([string]$file.target)
        $payload = Join-Path $base (SafePath ([string]$file.payload))
        $dest = Join-Path $root $rel
        if ($seen.ContainsKey($rel.ToLowerInvariant())) { throw "Повторення цілі: $rel" }
        $seen[$rel.ToLowerInvariant()] = $true
        if (-not (Test-Path -LiteralPath $payload -PathType Leaf) -or (Hash $payload) -ne [string]$file.sha256) { throw "Відсутній або змінений payload: $payload" }
        $existed = Test-Path -LiteralPath $dest -PathType Leaf
        if ((Test-Path -LiteralPath $dest) -and -not $existed) { throw "Шлях зайнятий папкою: $dest" }
        $rows += [pscustomobject]@{ target = [string]$file.target; payload = [string]$file.payload; installed = [string]$file.sha256; existed = $existed; original = $(if ($existed) { Hash $dest } else { '' }); backup = 'Original\' + $rel }
    }
    if ($adopting) { PrepareOriginalRows $root $rows }
    if ($manifest.baseline -and -not $adopting) {
        foreach ($entry in @($manifest.baseline)) {
            $p = Join-Path $root (SafePath ([string]$entry.target))
            if (-not (Test-Path -LiteralPath $p) -or (Hash $p) -ne [string]$entry.sha256) { throw "Версія оригінальної гри не відповідає збірці: $p" }
        }
    }
    foreach ($absent in $(if ($adopting) { @() } else { @($manifest.require_absent) })) {
        $p = Join-Path $root (SafePath ([string]$absent))
        if (Test-Path -LiteralPath $p) { throw "Це не чиста установка гри: уже є $p" }
    }
    $createdDirectories = @(CreatedDirectories $root $rows)
    [IO.Directory]::CreateDirectory($stateDir) | Out-Null
    $state = [pscustomobject]@{ schema = 1; game = [string]$manifest.game; phase = 'prepared'; files = $rows; restore_scope = 'original'; created_dirs = $createdDirectories; cleanup_legacy = $adopting }
    $adoptionRollback = @()
    try {
        if ($adopting) {
            foreach ($file in $manifest.files) {
                $rel = SafePath ([string]$file.target); $dest = Join-Path $root $rel
                $exists = Test-Path -LiteralPath $dest -PathType Leaf
                $savedRow = [pscustomobject]@{ target = [string]$file.target; existed = $exists; original = $(if ($exists) { Hash $dest } else { '' }); backup = 'BeforeInstall\' + $rel }
                if ($exists) {
                    $saved = Join-Path $stateDir $savedRow.backup
                    [IO.Directory]::CreateDirectory((Split-Path -Parent $saved)) | Out-Null
                    AtomicCopy $dest $saved ([string]$savedRow.original)
                }
                $adoptionRollback += $savedRow
            }
        }
        UpdateProgress 'Резервне копіювання оригіналів…' 20
        foreach ($row in $rows) {
            if ($row.existed) {
                $dest = Join-Path $root (SafePath ([string]$row.target))
                $bk = Join-Path $stateDir (SafePath ([string]$row.backup))
                [IO.Directory]::CreateDirectory((Split-Path -Parent $bk)) | Out-Null
                $originalSource = $(if ($adopting) { [string]$row.original_source } else { $dest })
                Copy-Item -LiteralPath $originalSource -Destination $bk -ErrorAction Stop
                if ((Hash $bk) -ne [string]$row.original) { throw "Backup не пройшов перевірку: $bk" }
            }
        }
        StateSave $statePath $state
        $state.phase = 'writing'; StateSave $statePath $state
        $index = 0
        foreach ($row in $rows) {
            $index++
            UpdateProgress ('Установлення ' + [string]$row.target) ([int](25 + 65 * $index / $rows.Count))
            $payload = Join-Path $base (SafePath ([string]$row.payload))
            $dest = Join-Path $root (SafePath ([string]$row.target))
            AtomicCopy $payload $dest ([string]$row.installed)
        }
        $state.phase = 'installed'; StateSave $statePath $state
        if ($adopting) { Remove-Item -LiteralPath (Join-Path $stateDir 'BeforeInstall') -Recurse -Force -ErrorAction SilentlyContinue }
        UpdateProgress 'Усі файли записані та перевірені.' 100
    } catch {
        $err = $_
        if (Test-Path -LiteralPath $statePath) {
            try {
                if ($adopting) { RestoreRows $root $stateDir $adoptionRollback $false } else { RestoreRows $root $stateDir $state $false }
                Remove-Item -LiteralPath $stateDir -Recurse -Force
            } catch { throw "Помилка встановлення: $err`nАвтовідновлення не завершилося: $_`nЗбережено backup: $stateDir" }
        } else { Remove-Item -LiteralPath $stateDir -Recurse -Force }
        throw $err
    }
}
function ImportOriginalState([string]$root, [string]$stateDir, [string]$statePath) {
    if ([string]$manifest.slug -ne 'townfall') { throw 'Не знайдено стан цієї установки для відновлення.' }
    if (Test-Path -LiteralPath $stateDir) { throw "Знайдено незавершений backup без стану: $stateDir" }
    $rows = @(); $seen = @{}
    foreach ($file in $manifest.files) {
        $rel = SafePath ([string]$file.target); $key = $rel.ToLowerInvariant()
        if ($seen.ContainsKey($key)) { throw "Повторення цілі: $rel" }
        $seen[$key] = $true
        $dest = Join-Path $root $rel
        if ((Test-Path -LiteralPath $dest) -and -not (Test-Path -LiteralPath $dest -PathType Leaf)) { throw "Шлях зайнятий папкою: $dest" }
        $rows += [pscustomobject]@{ target = [string]$file.target; installed = ''; existed = $false; original = ''; backup = 'Original\' + $rel }
    }
    # Resolve every genuine original before creating state or changing game files.
    PrepareOriginalRows $root $rows
    [IO.Directory]::CreateDirectory($stateDir) | Out-Null
    try {
        foreach ($row in $rows) {
            if ($row.existed) {
                $saved = Join-Path $stateDir (SafePath ([string]$row.backup))
                AtomicCopy ([string]$row.original_source) $saved ([string]$row.original)
            }
        }
        $state = [pscustomobject]@{schema=1;game=[string]$manifest.game;phase='restoring';files=$rows;restore_scope='original';created_dirs=@();cleanup_legacy=$true}
        StateSave $statePath $state
    } catch {
        if (-not (Test-Path -LiteralPath $statePath)) { Remove-Item -LiteralPath $stateDir -Recurse -Force -ErrorAction SilentlyContinue }
        throw
    }
}

function Restore([string]$root) {
    UpdateProgress 'Перевірка стану для відновлення…' 10
    CheckGame $root
    $stateDir = Join-Path $root ('.ColdVoiceInstaller\' + (SafePath ([string]$manifest.slug)))
    $statePath = Join-Path $stateDir 'state.json'
    if (-not (Test-Path -LiteralPath $statePath)) { ImportOriginalState $root $stateDir $statePath }
    $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($state.game -ne $manifest.game) { throw 'Стан належить іншій грі.' }
    if ($state.phase -eq 'updating') { $state = RecoverUpdate $root $stateDir $statePath $state }
    $scope = RestoreScope $state
    if ($state.phase -eq 'prepared') { throw "Установка перервана до запису файлів. Backup збережено: $stateDir" }
    if ($state.phase -notin @('installed', 'writing', 'restoring')) { throw "Невідомий стан: $($state.phase)" }
    # Validate backups first. During interrupted restore some destinations may
    # already contain original bytes, so only the first pass checks mod hashes.
    foreach ($row in @($state.files)) {
        $dest = Join-Path $root (SafePath ([string]$row.target))
        if ((Test-Path -LiteralPath $dest) -and -not (Test-Path -LiteralPath $dest -PathType Leaf)) { throw "Шлях для відновлення зайнятий папкою: $dest" }
        # Restore deliberately replaces changed/missing mod files with verified originals.
        if ($row.existed) {
            $bk = Join-Path $stateDir (SafePath ([string]$row.backup))
            if (-not (Test-Path -LiteralPath $bk) -or (Hash $bk) -ne [string]$row.original) { throw "Пошкоджений backup: $bk" }
        }
    }
    $state.phase = 'restoring'; StateSave $statePath $state
    RestoreRows $root $stateDir $state $false
    Remove-Item -LiteralPath $stateDir -Recurse -Force
    $legacyCleanup = [bool]($state.cleanup_legacy -or $state.PSObject.Properties.Name -notcontains 'created_dirs')
    CleanupDirectories $root $state.created_dirs $legacyCleanup
    UpdateProgress 'Оригінальні файли відновлено; файли й порожні папки інсталятора видалено.' 100
    return $scope
}
# The full installation wizard runs from the silent in-process EXE bundle.
$script:manifest = $manifest
function UpdateProgress([string]$message, [int]$percent) {
    if ($script:logBox) {
        $script:logBox.AppendText(($message + [Environment]::NewLine))
        $script:logBox.SelectionStart = $script:logBox.TextLength
        $script:logBox.ScrollToCaret()
    }
    if ($script:progressLabel) { $script:progressLabel.Text = $message }
    if ($script:progressFill -and $percent -ge 0) { $script:progressFill.Width = [int]($script:progressTrack.Width * [Math]::Min(100, [Math]::Max(0, $percent)) / 100) }
    [Windows.Forms.Application]::DoEvents()
}
$form = New-Object ColdVoiceShadowForm
$iconFile = Join-Path $base 'INSTALLER.ico'
if (Test-Path -LiteralPath $iconFile -PathType Leaf) {
    try { $form.Icon = New-Object System.Drawing.Icon -ArgumentList $iconFile }
    catch { $form.Icon = [Drawing.SystemIcons]::Application }
}
$form.Text = 'ColdVoice — майстер установлення'
$form.Size = New-Object Drawing.Size(760,580)
$form.StartPosition = 'CenterScreen'
$form.MinimumSize = $form.Size
$form.MaximizeBox = $false
$form.FormBorderStyle = [Windows.Forms.FormBorderStyle]::None
$form.ShowInTaskbar = $true
$topBar = New-Object Windows.Forms.Panel
$topBar.Dock = [Windows.Forms.DockStyle]::Top
$topBar.Height = 58
$topBar.BackColor = [Drawing.Color]::FromArgb(22,27,34)
$form.Controls.Add($topBar)
$topAccent = New-Object Windows.Forms.Panel
$topAccent.Location = New-Object Drawing.Point(0,0)
$topAccent.Size = New-Object Drawing.Size(4,58)
$topAccent.BackColor = [Drawing.Color]::FromArgb(83,165,213)
$topBar.Controls.Add($topAccent)
$topDivider = New-Object Windows.Forms.Panel
$topDivider.Location = New-Object Drawing.Point(4,56)
$topDivider.Size = New-Object Drawing.Size(756,2)
$topDivider.BackColor = [Drawing.Color]::FromArgb(48,66,82)
$topBar.Controls.Add($topDivider)
$topIcon = New-Object Windows.Forms.PictureBox
$topIcon.Location = New-Object Drawing.Point(20,13)
$topIcon.Size = New-Object Drawing.Size(32,32)
$topIcon.SizeMode = [Windows.Forms.PictureBoxSizeMode]::Zoom
$previewFile = Join-Path $base 'INSTALLER.png'
if (Test-Path -LiteralPath $previewFile -PathType Leaf) {
    try { $topIcon.Image = [Drawing.Image]::FromFile($previewFile) }
    catch { $topIcon.Image = $null }
}
$topBar.Controls.Add($topIcon)
$topText = New-Object Windows.Forms.Label
$topText.Text = 'COLDVOICE'
$topText.Location = New-Object Drawing.Point(63,7)
$topText.Size = New-Object Drawing.Size(500,27)
$topText.Font = New-Object Drawing.Font('Segoe UI',13,[Drawing.FontStyle]::Bold)
$topBar.Controls.Add($topText)
$topSub = New-Object Windows.Forms.Label
$topSub.Text = ([string]$manifest.game).ToUpperInvariant() + '  /  УКРАЇНСЬКА ЛОКАЛІЗАЦІЯ'
$topSub.Location = New-Object Drawing.Point(64,33)
$topSub.Size = New-Object Drawing.Size(530,19)
$topSub.Font = New-Object Drawing.Font('Segoe UI',8)
$topBar.Controls.Add($topSub)
$topMin = New-Object Windows.Forms.Button
$topMin.Text = '─'
$topMin.Location = New-Object Drawing.Point(656,11)
$topMin.Size = New-Object Drawing.Size(42,34)
$topMin.Add_Click({ $form.WindowState = [Windows.Forms.FormWindowState]::Minimized })
$topBar.Controls.Add($topMin)
$topClose = New-Object Windows.Forms.Button
$topClose.Text = ''
$topClose.AccessibleName = 'Закрити'
$topClose.Location = New-Object Drawing.Point(702,11)
$topClose.Size = New-Object Drawing.Size(42,34)
$topClose.Add_Paint({
    param($sender, $e)
    # Draw the cross around the actual button centre, independent of font metrics and DPI.
    $cx = ($sender.ClientSize.Width - 1) / 2.0
    $cy = ($sender.ClientSize.Height - 1) / 2.0
    $pen = [Drawing.Pen]::new([Drawing.Color]::FromArgb(228,235,241), [single]1.8)
    try {
        $e.Graphics.SmoothingMode = [Drawing.Drawing2D.SmoothingMode]::AntiAlias
        $e.Graphics.DrawLine($pen, [single]($cx - 5), [single]($cy - 5), [single]($cx + 5), [single]($cy + 5))
        $e.Graphics.DrawLine($pen, [single]($cx + 5), [single]($cy - 5), [single]($cx - 5), [single]($cy + 5))
    } finally { $pen.Dispose() }
})
$topClose.Add_Click({ if (-not $script:busy) { $form.Close() } })
$topBar.Controls.Add($topClose)
$dragWindow = {
    if ($_.Button -eq [Windows.Forms.MouseButtons]::Left) {
        [ColdVoiceWindowApi]::ReleaseCapture() | Out-Null
        [ColdVoiceWindowApi]::SendMessage($form.Handle, 0xA1, 2, 0) | Out-Null
    }
}
$topBar.Add_MouseDown($dragWindow)
$topText.Add_MouseDown($dragWindow)
$topSub.Add_MouseDown($dragWindow)
$topIcon.Add_MouseDown($dragWindow)
$heading = New-Object Windows.Forms.Label
$heading.Text = 'ColdVoice — повна українська локалізація'
$heading.Location = New-Object Drawing.Point(22,82)
$heading.Size = New-Object Drawing.Size(700,35)
$heading.Font = New-Object Drawing.Font('Segoe UI',17,[Drawing.FontStyle]::Bold)
$form.Controls.Add($heading)
$stepLabel = New-Object Windows.Forms.Label
$stepLabel.Location = New-Object Drawing.Point(24,124); $stepLabel.Size = New-Object Drawing.Size(700,28)
$form.Controls.Add($stepLabel)
$page1 = New-Object Windows.Forms.Panel
$page2 = New-Object Windows.Forms.Panel
$page3 = New-Object Windows.Forms.Panel
$page4 = New-Object Windows.Forms.Panel
foreach ($page in @($page1,$page2,$page3,$page4)) {
    $page.Location = New-Object Drawing.Point(20,166)
    $page.Size = New-Object Drawing.Size(710,300)
    $form.Controls.Add($page)
}
$gameLabel = New-Object Windows.Forms.Label
$gameLabel.Text = [string]$manifest.game
$gameLabel.Location = New-Object Drawing.Point(4,8); $gameLabel.Size = New-Object Drawing.Size(680,32)
$gameLabel.Font = New-Object Drawing.Font('Segoe UI',14,[Drawing.FontStyle]::Bold)
$page1.Controls.Add($gameLabel)
$versionLabel = New-Object Windows.Forms.Label
$versionLabel.Text = 'Локалізацію перевірено на збірках гри: ' + [string]$manifest.tested_version
$versionLabel.Location = New-Object Drawing.Point(4,46)
$versionLabel.Size = New-Object Drawing.Size(680,27)
$versionLabel.Font = New-Object Drawing.Font('Segoe UI',10)
$page1.Controls.Add($versionLabel)
$pathLabel = New-Object Windows.Forms.Label
$pathLabel.Text = 'Коренева папка гри'
$pathLabel.Location = New-Object Drawing.Point(4,80); $pathLabel.Size = New-Object Drawing.Size(680,24)
$page1.Controls.Add($pathLabel)
$path = New-Object Windows.Forms.TextBox
$path.Location = New-Object Drawing.Point(4,115); $path.Size = New-Object Drawing.Size(550,29)
$page1.Controls.Add($path)
$browse = New-Object Windows.Forms.Button
$browse.Text = 'Огляд…'; $browse.Location = New-Object Drawing.Point(566,110); $browse.Size = New-Object Drawing.Size(105,35)
$browse.Add_Click({
    $browse.Enabled = $false
    try {
        $form.Activate()
        $initialFolder = $path.Text.Trim()
        if (-not [IO.Directory]::Exists($initialFolder)) { $initialFolder = '' }
        $selectedFolder = [ColdVoiceFolderPicker]::Select($form.Handle, $initialFolder)
        if (-not [string]::IsNullOrWhiteSpace($selectedFolder)) { $path.Text = $selectedFolder }
    } catch {
        [Windows.Forms.MessageBox]::Show($form, ('Не вдалося відкрити вибір папки: ' + [string]$_), 'ColdVoice', 'OK', 'Error') | Out-Null
    } finally {
        $browse.Enabled = $true
        $form.Activate()
        $path.Focus() | Out-Null
    }
})
$page1.Controls.Add($browse)
$hint = New-Object Windows.Forms.Label
$hint.Text = 'Оберіть папку гри. Можна встановити або оновити ColdVoice. Закрийте гру перед продовженням.'
$hint.Location = New-Object Drawing.Point(4,172); $hint.Size = New-Object Drawing.Size(675,65)
$page1.Controls.Add($hint)
$summary = New-Object Windows.Forms.TextBox
$summary.Multiline = $true; $summary.ReadOnly = $true; $summary.ScrollBars = 'Vertical'
$summary.Location = New-Object Drawing.Point(4,5); $summary.Size = New-Object Drawing.Size(675,260)
$page2.Controls.Add($summary)
$progressLabel = New-Object Windows.Forms.Label
$progressLabel.Text = 'Підготовка…'
$progressLabel.Location = New-Object Drawing.Point(4,10); $progressLabel.Size = New-Object Drawing.Size(670,36)
$page3.Controls.Add($progressLabel)
$progressTrack = New-Object Windows.Forms.Panel
$progressTrack.Location = New-Object Drawing.Point(4,52); $progressTrack.Size = New-Object Drawing.Size(670,12)
$progressTrack.BackColor = [Drawing.Color]::FromArgb(41,49,60)
$progressFill = New-Object Windows.Forms.Panel
$progressFill.Location = New-Object Drawing.Point(0,0); $progressFill.Size = New-Object Drawing.Size(1,12)
$progressFill.BackColor = [Drawing.Color]::FromArgb(91,165,216)
$progressTrack.Controls.Add($progressFill)
$page3.Controls.Add($progressTrack)
$logBox = New-Object Windows.Forms.TextBox
$logBox.Multiline = $true; $logBox.ReadOnly = $true; $logBox.ScrollBars = 'Vertical'
$logBox.Location = New-Object Drawing.Point(4,85); $logBox.Size = New-Object Drawing.Size(675,180)
$page3.Controls.Add($logBox)
$resultLabel = New-Object Windows.Forms.Label
$resultLabel.Location = New-Object Drawing.Point(4,20); $resultLabel.Size = New-Object Drawing.Size(675,210)
$resultLabel.Font = New-Object Drawing.Font('Segoe UI',12)
$page4.Controls.Add($resultLabel)
$footer = New-Object Windows.Forms.Panel
$footer.Location = New-Object Drawing.Point(0,494)
$footer.Size = New-Object Drawing.Size(760,86)
$footer.BackColor = [Drawing.Color]::FromArgb(20,26,34)
$form.Controls.Add($footer)
$back = New-Object Windows.Forms.Button
$back.Text = 'Назад'; $back.Location = New-Object Drawing.Point(365,26); $back.Size = New-Object Drawing.Size(110,34)
$footer.Controls.Add($back)
$next = New-Object Windows.Forms.Button
$next.Text = 'Далі'; $next.Location = New-Object Drawing.Point(488,26); $next.Size = New-Object Drawing.Size(110,34)
$footer.Controls.Add($next)
$restoreButton = New-Object Windows.Forms.Button
$restoreButton.Text = 'Відновити до оригіналу'; $restoreButton.Location = New-Object Drawing.Point(22,26); $restoreButton.Size = New-Object Drawing.Size(225,34)
$footer.Controls.Add($restoreButton)
$closeButton = New-Object Windows.Forms.Button
$closeButton.Text = 'Закрити'; $closeButton.Location = New-Object Drawing.Point(628,26); $closeButton.Size = New-Object Drawing.Size(110,34)
$closeButton.Add_Click({ if (-not $script:busy) { $form.Close() } })
$footer.Controls.Add($closeButton)
function ShowStep([int]$step) {
    $script:step = $step
    $pages = @($page1,$page2,$page3,$page4)
    for ($i=0; $i -lt $pages.Count; $i++) { $pages[$i].Visible = ($i -eq $step) }
    $stepLabel.Text = @('1 / 4 — Вибір гри', '2 / 4 — Перевірка комплекту', '3 / 4 — Установлення або відновлення', '4 / 4 — Результат')[$step]
    $back.Enabled = ($step -eq 1)
    $next.Enabled = ($step -eq 0 -or $step -eq 1)
    $next.Text = $(if ($step -eq 1 -and $script:upgrading) { 'Оновити' } elseif ($step -eq 1) { 'Встановити' } else { 'Далі' })
    $restoreButton.Enabled = ($step -eq 1)
    $closeButton.Enabled = -not $script:busy
}
$back.Add_Click({ if ($script:step -eq 1) { ShowStep 0 } })
$next.Add_Click({
    if ($script:step -eq 0) {
        try {
            if (-not (Test-Path -LiteralPath $path.Text -PathType Container)) { throw 'Оберіть існуючу папку гри.' }
            CheckGame $path.Text
            $statePath = Join-Path $path.Text ('.ColdVoiceInstaller\' + (SafePath ([string]$script:manifest.slug)) + '\state.json')
            $script:upgrading = Test-Path -LiteralPath $statePath
            $scope = 'original'
            if ($script:upgrading) {
                $selectedState = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
                $scope = RestoreScope $selectedState
                $stateText = 'ColdVoice уже встановлено. Буде встановлено нову версію зі збереженням первинного backup.'
            } elseif (ExistingColdVoice $path.Text) {
                $script:upgrading = $true
                $stateText = 'Знайдено попередню ColdVoice. Буде встановлено нову версію; справжні оригінали перевіряються за SHA перед записом.'
            } else { $stateText = 'Готово до встановлення.' }
            $restoreButton.Text = 'Відновити до оригіналу'
            $summary.Text = ('Гра: ' + $script:manifest.game + [Environment]::NewLine +
                'Локалізацію перевірено на збірках гри: ' + [string]$script:manifest.tested_version + [Environment]::NewLine +
                'Папка: ' + $path.Text + [Environment]::NewLine +
                'Стан: ' + $stateText + [Environment]::NewLine + [Environment]::NewLine +
                'Будуть перевірені та встановлені файли:' + [Environment]::NewLine +
                ((@($script:manifest.files) | ForEach-Object { '  • ' + [string]$_.target }) -join [Environment]::NewLine) +
                [Environment]::NewLine + [Environment]::NewLine +
                'До заміни буде створено резервні копії. Після запису контрольні суми перевіряються повторно.')
            ShowStep 1
        } catch { [Windows.Forms.MessageBox]::Show([string]$_, 'Перевірка гри', 'OK', 'Error') | Out-Null }
    } elseif ($script:step -eq 1) {
        ShowStep 2
        $script:busy = $true; $back.Enabled = $false; $next.Enabled = $false; $closeButton.Enabled = $false
        try {
            Install $path.Text
            $resultLabel.Text = 'Локалізацію встановлено і файли перевірено.' + [Environment]::NewLine +
                'Повністю перезапустіть гру. Для повернення оригіналу знову запустіть цей EXE і натисніть «Відновити до оригіналу».'
            ShowStep 3
        } catch {
            UpdateProgress ('ПОМИЛКА: ' + [string]$_) -1
            $resultLabel.Text = 'Установлення не завершено:' + [Environment]::NewLine + [string]$_ + [Environment]::NewLine +
                'Деталі залишилися у вікні ходу установки.'
            ShowStep 3
        } finally { $script:busy = $false; $closeButton.Enabled = $true; $back.Enabled = $false }
    }
})
$restoreButton.Add_Click({
    ShowStep 2
    $script:busy = $true; $back.Enabled = $false; $next.Enabled = $false; $closeButton.Enabled = $false
    try {
        $restoreScope = Restore $path.Text
        $resultLabel.Text = 'Оригінальні файли відновлено. Повністю перезапустіть гру.'
        ShowStep 3
    } catch {
        UpdateProgress ('ПОМИЛКА: ' + [string]$_) -1
        $resultLabel.Text = 'Відновлення не завершено:' + [Environment]::NewLine + [string]$_
        ShowStep 3
    } finally { $script:busy = $false; $closeButton.Enabled = $true; $back.Enabled = $false }
})
$form.Add_FormClosing({ if ($script:busy) { $_.Cancel = $true } })

function ApplyDarkTheme($control) {
    $control.BackColor = [Drawing.Color]::FromArgb(17,21,27)
    $control.ForeColor = [Drawing.Color]::FromArgb(228,235,241)
    foreach ($child in $control.Controls) {
        ApplyDarkTheme $child
        if ($child -is [Windows.Forms.Button]) {
            $child.FlatStyle = [Windows.Forms.FlatStyle]::Flat
            $child.BackColor = [Drawing.Color]::FromArgb(35,46,57)
            $child.FlatAppearance.BorderColor = [Drawing.Color]::FromArgb(75,105,128)
            $child.Cursor = [Windows.Forms.Cursors]::Hand
        } elseif ($child -is [Windows.Forms.TextBox]) {
            $child.BackColor = [Drawing.Color]::FromArgb(24,30,38)
            $child.BorderStyle = [Windows.Forms.BorderStyle]::FixedSingle
            $child.ForeColor = [Drawing.Color]::FromArgb(228,235,241)
        }
    }
}
ApplyDarkTheme $form
$topBar.BackColor = [Drawing.Color]::FromArgb(22,27,34)
$topText.BackColor = $topBar.BackColor
$topSub.BackColor = $topBar.BackColor
$topText.ForeColor = [Drawing.Color]::FromArgb(235,241,247)
$topSub.ForeColor = [Drawing.Color]::FromArgb(123,177,210)
$topIcon.BackColor = [Drawing.Color]::FromArgb(22,27,34)
$topAccent.BackColor = [Drawing.Color]::FromArgb(83,165,213)
$topDivider.BackColor = [Drawing.Color]::FromArgb(48,66,82)
$footer.BackColor = [Drawing.Color]::FromArgb(20,26,34)
$topMin.BackColor = [Drawing.Color]::FromArgb(22,27,34)
$topClose.BackColor = [Drawing.Color]::FromArgb(40,31,39)
$form.Font = New-Object Drawing.Font('Segoe UI',10)
$heading.ForeColor = [Drawing.Color]::FromArgb(237,244,249)
$gameLabel.ForeColor = [Drawing.Color]::FromArgb(137,194,229)
$progressTrack.BackColor = [Drawing.Color]::FromArgb(41,49,60)
$progressFill.BackColor = [Drawing.Color]::FromArgb(91,165,216)
$next.BackColor = [Drawing.Color]::FromArgb(38,102,145)
ShowStep 0
[Windows.Forms.Application]::Run($form)
