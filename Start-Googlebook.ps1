[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$LauncherArgs
)
Set-Location -Path $PSScriptRoot

$pythonCmd = Get-Command "python" -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    Write-Error "Python was not found in PATH. Please install Python 3.10+ from python.org or Microsoft Store."
    exit 1
}

& python "launcher\launch_googlebook.py" @LauncherArgs
