# Run via: node run.js pwsh -File perms_win.ps1
# Prints the pipe's security descriptor and probes access as a second, non-admin local user.
$ErrorActionPreference = 'Stop'
$pipe = $env:SPIKE_PATH
$out = @()

$out += "current user: $(whoami)"
$out += (whoami /groups | Select-String 'Mandatory Label|BUILTIN\\Administrators' | ForEach-Object { $_.Line.Trim() })
$out += (python perms_win.py sddl $pipe)
$out += "as pipe owner:"
$out += (python perms_win.py open $pipe)

$out += "as a second non-admin local user:"
try {
  $name = 'spikeuser'
  $plain = 'Sp1ke-' + [guid]::NewGuid().ToString('N').Substring(0, 12) + '!a'
  $pw = ConvertTo-SecureString $plain -AsPlainText -Force
  New-LocalUser -Name $name -Password $pw | Out-Null
  $cred = [pscredential]::new("$env:COMPUTERNAME\$name", $pw)
  $dir = 'C:\spike-pub'
  New-Item -ItemType Directory -Force $dir | Out-Null
  icacls $dir /grant 'Users:(OI)(CI)M' | Out-Null
  Copy-Item perms_win.py $dir
  $py = (Get-Command python).Source
  $proc = Start-Process -FilePath $py -ArgumentList "$dir\perms_win.py", 'open', $pipe `
    -Credential $cred -WorkingDirectory $dir -Wait -PassThru `
    -RedirectStandardOutput "$dir\out.txt" -RedirectStandardError "$dir\err.txt"
  $out += "exit code: $($proc.ExitCode)"
  $out += (Get-Content "$dir\out.txt")
  $out += (Get-Content "$dir\err.txt")
} catch {
  $out += "second-user probe could not run: $_"
}

$out | ForEach-Object { Write-Host $_ }
if ($env:GITHUB_STEP_SUMMARY) {
  "**windows named pipe access**`n`n``````n$($out -join "`n")`n``````n" | Add-Content $env:GITHUB_STEP_SUMMARY
}
