$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
$picker=New-Object System.Windows.Forms.OpenFileDialog
$picker.Title='Select the exact Resonance EXE uploaded to Nexus'
$picker.Filter='Windows installer (*.exe)|*.exe'
if($picker.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK){exit 0}
try {
    $python=Get-Command python.exe -ErrorAction SilentlyContinue
    if(-not $python){
        $candidate='F:\MyPrograms\Mods\Dubl\GameDub_UA_Studio_v0.1\GameDub_UA_Studio_Fix_New_UA-EN\OmniVoice\venv\Scripts\python.exe'
        if(Test-Path -LiteralPath $candidate){$runner=$candidate}else{throw 'Python not found. Use the existing GameDub Python environment.'}
    }else{$runner=$python.Source}
    $tag=(Get-Date -Format 'yyyyMMdd_HHmmss')+'_'+[Guid]::NewGuid().ToString('N').Substring(0,6)
    $output=Join-Path (Split-Path -Parent $PSScriptRoot) ('Resonance_EXE_Review_'+$tag)
    & $runner (Join-Path $PSScriptRoot 'extract_review.py') $picker.FileName --output $output
    if($LASTEXITCODE -ne 0){throw 'Collection failed; see the message in the console.'}
    [System.Windows.Forms.MessageBox]::Show(('Send the generated review ZIP to the chat:'+[Environment]::NewLine+$output+'.zip'),'Resonance review') | Out-Null
    Start-Process explorer.exe -ArgumentList ('/select,"'+$output+'.zip"')
}catch{[System.Windows.Forms.MessageBox]::Show($_.Exception.Message,'Review failed') | Out-Null;exit 1}
