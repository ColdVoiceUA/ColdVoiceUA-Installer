# COLDVOICE_RESONANCE_INSTALLER_LIFECYCLE_V3
# Resonance-only operations. The installed Townfall functions stay intact.
if ($manifest.mode -eq 'resonance-approved-wem-v1') {
    function ResonancePath([string]$root,[string]$relative) { return [ResonancePckEngine]::PathUnder($root,$relative) }
    function ResonanceHash([string]$path) { return [ResonancePckEngine]::Hash($path) }
    function ResonanceState([string]$root) { return (ResonancePath $root ('.ColdVoiceInstaller/' + [string]$manifest.slug)) }
    function ResonanceRemoveEmptyRoot([string]$root) {
        $parent = ResonancePath $root '.ColdVoiceInstaller'
        if (Test-Path -LiteralPath $parent -PathType Container) {
            # Nonrecursive deletion preserves any other profile or unexpected file.
            try { [IO.Directory]::Delete($parent,$false) } catch [IO.IOException] { }
        }
    }
    function CheckGame([string]$root) {
        if ($script:previewOnly) { return }
        $exe = ResonancePath $root ([string]$manifest.game_exe)
        $structure = ResonancePath $root ([string]$manifest.pck.structure)
        $target = ResonancePath $root ([string]$manifest.pck.target)
        if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw 'Оберіть кореневу папку Resonance із відповідним EXE.' }

        if ($manifest.process -and @(Get-Process -Name ([string]$manifest.process) -ErrorAction SilentlyContinue).Count) { throw 'Повністю закрийте Resonance перед установленням або відновленням.' }
    }
    function Install([string]$root) {
        if ($script:previewOnly) { return }
        [ResonancePckEngine]::Status = [Action[string,int]] { param($message,$percent) UpdateProgress $message $percent }
        [ResonancePckEngine]::HashProgress = 5
        CheckGame $root
        $structure = ResonancePath $root ([string]$manifest.pck.structure)
        if (-not (Test-Path -LiteralPath $structure -PathType Leaf) -or (ResonanceHash $structure) -ne [string]$manifest.pck.structure_sha256) { throw 'VO_STRUCTURE не відповідає перевіреній версії гри.' }
        UpdateProgress 'Перевірка оригіналу та українського пакета…' 5
        $target = ResonancePath $root ([string]$manifest.pck.target)
        $dir = ResonanceState $root; $stateFile = Join-Path $dir 'state.json'; $original = Join-Path $dir 'original.pck'
        $state = $null; $new = -not (Test-Path -LiteralPath $stateFile)
        if (-not $new) {
            $state = Get-Content -LiteralPath $stateFile -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($state.schema -ne 1 -or $state.mode -ne 'resonance-approved-wem-v1' -or $state.target -ne $manifest.pck.target -or $state.base_sha256 -ne $manifest.pck.base_sha256 -or $state.phase -ne 'installed') { throw 'Основа пакета відрізняється від збереженого оригіналу або операцію перервано. Натисніть «Відновити до оригіналу», після чого встановіть сумісний пакет. Стан і резерв не видаляйте.' }
            if ((ResonanceHash $target) -ne [string]$state.installed_sha256) { throw 'PCK змінено після встановлення. Оновлення зупинено.' }
            if (-not (Test-Path -LiteralPath $original) -or (ResonanceHash $original) -ne [string]$manifest.pck.base_sha256) { throw 'Початкова резервна копія пошкоджена.' }
            $source = $original
        } else {
            if (Test-Path -LiteralPath $dir) { throw 'Знайдено незавершену установку. Збережені резервні файли не перезаписуються.' }
            if ((ResonanceHash $target) -ne [string]$manifest.pck.base_sha256) { throw 'Потрібен оригінальний VO_MEDIA цієї версії гри. Якщо озвучку встановлено через GameDub, спочатку відновіть оригінал через «Збірка».' }
            $source = $target
        }
        $needed = [long]$manifest.pck.output_size + $(if ($new) { [long]$manifest.pck.base_size } else { 0 }) + 67108864
        $drive = New-Object IO.DriveInfo -ArgumentList ([IO.Path]::GetPathRoot([IO.Path]::GetFullPath($target)))
        if ($drive.AvailableFreeSpace -lt $needed) { throw 'Недостатньо вільного місця для нового PCK та резервної копії.' }
        $temp = $target + '.coldvoice-new'; $previous = $target + '.coldvoice-previous'
        if ((Test-Path -LiteralPath $temp) -or (Test-Path -LiteralPath $previous)) { throw 'Є файли перерваної установки. Вони не будуть перезаписані.' }
        $package = $(if ($env:COLDVOICE_UA_ROOT) { $env:COLDVOICE_UA_ROOT } else { $base })
        $swapped = $false; $committed = $false; $oldState = $null
        if (-not $new) { $oldState = [IO.File]::ReadAllBytes($stateFile) }
        try {
            $callback = [Action[string,int]] { param($message,$percent) UpdateProgress $message $percent }
            [ResonancePckEngine]::Build($source,$temp,(Join-Path $base 'manifest.json'),$package,$callback) | Out-Null
            if ($new) {
                [IO.Directory]::CreateDirectory($dir) | Out-Null
                UpdateProgress 'Збереження оригінального PCK…' 94
                [ResonancePckEngine]::CopyOriginal($target,$original)
                if ((ResonanceHash $original) -ne [string]$manifest.pck.base_sha256) { throw 'Резервна копія не пройшла перевірку.' }
            }
            # Check again after the long rebuild, before switching the live file.
            $expected = $(if ($new) { [string]$manifest.pck.base_sha256 } else { [string]$state.installed_sha256 })
            if ((ResonanceHash $target) -ne $expected) { throw 'Файл гри змінився під час підготовки. Заміна зупинена.' }
            $nextState = [pscustomobject]@{schema=1;mode='resonance-approved-wem-v1';target=[string]$manifest.pck.target;base_sha256=[string]$manifest.pck.base_sha256;installed_sha256=[string]$manifest.pck.output_sha256;previous_sha256=$expected;phase='writing';count=@($manifest.pck.replacements).Count}
            StateSave $stateFile $nextState
            Move-Item -LiteralPath $target -Destination $previous -ErrorAction Stop
            try { Move-Item -LiteralPath $temp -Destination $target -ErrorAction Stop; $swapped = $true }
            catch { Move-Item -LiteralPath $previous -Destination $target -ErrorAction Stop; throw }
            $nextState.phase='installed'; StateSave $stateFile $nextState; $committed=$true
            Remove-Item -LiteralPath $previous -Force
            UpdateProgress 'Українські репліки встановлено. Неозвучені записи збережено з оригіналу.' 100
        } catch {
            if (-not $committed) {
                if ($swapped -and (Test-Path -LiteralPath $previous)) {
                    Remove-Item -LiteralPath $target -Force; Move-Item -LiteralPath $previous -Destination $target
                }
                if (-not $new -and $oldState) { [IO.File]::WriteAllBytes($stateFile,$oldState) }
                elseif ($new -and (Test-Path -LiteralPath $dir) -and -not (Test-Path -LiteralPath $previous) -and (Test-Path -LiteralPath $target) -and (ResonanceHash $target) -eq [string]$manifest.pck.base_sha256) { Remove-Item -LiteralPath $dir -Recurse -Force }
            }
            throw
        } finally { if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force } }
    }
    function Restore([string]$root) {
        if ($script:previewOnly) { return }
        [ResonancePckEngine]::Status = [Action[string,int]] { param($message,$percent) UpdateProgress $message $percent }
        [ResonancePckEngine]::HashProgress = 10
        CheckGame $root
        $target = ResonancePath $root ([string]$manifest.pck.target); $dir=ResonanceState $root
        $stateFile=Join-Path $dir 'state.json';$original=Join-Path $dir 'original.pck'
        if (-not (Test-Path -LiteralPath $stateFile)) { throw 'Немає установки Resonance для відновлення.' }
        $state=Get-Content -LiteralPath $stateFile -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($state.schema -ne 1 -or $state.mode -ne 'resonance-approved-wem-v1' -or $state.target -ne $manifest.pck.target -or $state.phase -notin @('installed','writing','restoring')) { throw 'Невідомий стан установки; резервні файли збережено.' }
        if ([string]$state.base_sha256 -notmatch '^[0-9a-fA-F]{64}$' -or [string]$state.installed_sha256 -notmatch '^[0-9a-fA-F]{64}$') { throw 'Некоректні контрольні суми стану установки.' }
        $previous=$target+'.coldvoice-previous'
        $targetHash=$(if(Test-Path -LiteralPath $target) {ResonanceHash $target} else {''})
        $previousHash=$(if(Test-Path -LiteralPath $previous) {ResonanceHash $previous} else {''})
        if ($state.phase -eq 'restoring' -and $targetHash -eq [string]$state.base_sha256) {
            if ($previousHash -and $previousHash -ne [string]$state.restore_previous_sha256) { throw 'Залишок відновлення змінено; файли збережено.' }
            if ($previousHash) {Remove-Item -LiteralPath $previous -Force}
            Remove-Item -LiteralPath $dir -Recurse -Force
            ResonanceRemoveEmptyRoot $root
            UpdateProgress 'Оригінальний PCK відновлено.' 100;return
        }
        if ($targetHash -and $targetHash -ne [string]$state.installed_sha256 -and -not ($state.phase -eq 'writing' -and $targetHash -eq [string]$state.previous_sha256)) { throw 'PCK змінено після установки. Відновлення зупинено.' }
        $expectedPrevious=$(if($state.phase -eq 'restoring') {[string]$state.restore_previous_sha256} else {[string]$state.previous_sha256})
        if ($previousHash -and $previousHash -ne $expectedPrevious) { throw 'Резервний файл перерваної заміни змінено.' }
        if (-not $targetHash -and -not $previousHash) { throw 'Немає підтвердженого поточного PCK або файлу перерваної заміни.' }
        if (-not (Test-Path -LiteralPath $original) -or (ResonanceHash $original) -ne [string]$state.base_sha256) { throw 'Оригінальна резервна копія пошкоджена.' }
        $state | Add-Member -NotePropertyName restore_previous_sha256 -NotePropertyValue $(if($previousHash){$previousHash}else{$targetHash}) -Force
        $state.phase='restoring';StateSave $stateFile $state
        if ($targetHash) {
            if ($previousHash) {Remove-Item -LiteralPath $target -Force}
            else {Move-Item -LiteralPath $target -Destination $previous}
        }
        Move-Item -LiteralPath $original -Destination $target
        Remove-Item -LiteralPath $previous -Force;Remove-Item -LiteralPath $dir -Recurse -Force
        ResonanceRemoveEmptyRoot $root
        UpdateProgress 'Оригінальний PCK відновлено.' 100
    }
}
