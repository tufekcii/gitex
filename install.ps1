<#
.SYNOPSIS
    gitex'i kurar: uv, Python 3.12 ve `gitex` komutu. Sonunda kurulum sihirbazını açar.
    Installs gitex: uv, Python 3.12 and the `gitex` command, then opens the setup wizard.

.DESCRIPTION
    Repo klonlandıktan sonra tek komut / One command after cloning:  .\install.cmd
    - uv yoksa resmi kurucusuyla kurar / installs uv with its official installer if missing
    - Python 3.12'yi uv indirir; sistemdeki Python'a dokunulmaz / uv downloads Python; system Python is untouched
    Tekrar çalıştırmak güvenlidir; güncelleme için de kullanılır / Safe to re-run; also used to update.

.PARAMETER Lang
    tr ya da en. Verilmezse sorulur / tr or en. Asked if not given.

.PARAMETER NoSetup
    Kurulumdan sonra sihirbazı başlatma / Don't start the setup wizard afterwards.

.PARAMETER NoModifyPath
    Kullanıcı PATH'ini değiştirme (CI ve test için) / Don't change the user PATH (for CI and tests).

.PARAMETER Uninstall
    gitex'i kaldır / Uninstall gitex.
#>
[CmdletBinding()]
param(
    [ValidateSet('tr', 'en', '')]
    [string]$Lang = '',
    [switch]$NoSetup,
    [switch]$NoModifyPath,
    [switch]$Uninstall
)

# 'Stop' kullanılmaz: Windows PowerShell 5.1, yerel programların (uv, git) stderr'e yazdığı
# zararsız uyarıları bile betiği durduran hataya çevirir. Hatalar $LASTEXITCODE ile denetlenir.
$ErrorActionPreference = 'Continue'
$Root = $PSScriptRoot
# Bu betiği başlatan terminalin PATH'i (alt süreç onu değiştiremez; sonda uyarmak için).
$CallerPath = $env:Path
$Interactive = -not [Console]::IsInputRedirected

# ---------------------------------------------------------------------- dil / language

if (-not $Lang) {
    $systemLang = if ((Get-UICulture).Name -like 'tr*' -or (Get-Culture).Name -like 'tr*') { 'tr' } else { 'en' }
    $Lang = $systemLang
    if ($Interactive -and -not $Uninstall) {
        $default = if ($systemLang -eq 'tr') { '1' } else { '2' }
        Write-Host 'Dil / Language' -ForegroundColor Cyan
        Write-Host '   1) Türkçe'
        Write-Host '   2) English'
        while ($true) {
            $answer = (Read-Host "Seçim / Choice [$default]").Trim()
            if (-not $answer) { $answer = $default }
            if ($answer -eq '1') { $Lang = 'tr'; break }
            if ($answer -eq '2') { $Lang = 'en'; break }
            Write-Host '1 / 2' -ForegroundColor Yellow
        }
        Write-Host ''
    }
}

function T([string]$Tr, [string]$En) { if ($Lang -eq 'tr') { $Tr } else { $En } }
function Step([string]$Message) { Write-Host "==> $Message" -ForegroundColor Cyan }
function Ok([string]$Message) { Write-Host "    $Message" -ForegroundColor Green }
function Fail([string]$Message, [string]$Hint) {
    Write-Host "$(T 'Hata' 'Error'): $Message" -ForegroundColor Red
    if ($Hint) { Write-Host "$(T 'İpucu' 'Hint'): $Hint" -ForegroundColor DarkGray }
    exit 1
}

function Find-Uv {
    $cmd = Get-Command uv -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($dir in @("$env:USERPROFILE\.local\bin", "$env:USERPROFILE\.cargo\bin")) {
        $candidate = Join-Path $dir 'uv.exe'
        if (Test-Path $candidate) { return $candidate }
    }
    return $null
}

$uv = Find-Uv

if ($Uninstall) {
    if (-not $uv) { Fail (T 'uv bulunamadı; gitex zaten kurulu görünmüyor.' 'uv not found; gitex does not seem to be installed.') }
    Step (T 'gitex kaldırılıyor' 'Uninstalling gitex')
    & $uv tool uninstall gitex
    Ok (T 'Kaldırıldı. Anahtar kasasındaki kayıtlar için önce: gitex auth logout' 'Removed. To clear stored keys first run: gitex auth logout')
    exit 0
}

Step (T 'git kontrol ediliyor' 'Checking git')
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Fail (T 'git bulunamadı.' 'git not found.') (T 'Kurun: https://git-scm.com/download/win  (ya da: winget install Git.Git)' 'Install it: https://git-scm.com/download/win  (or: winget install Git.Git)')
}
Ok (git --version)

if (-not $uv) {
    Step (T 'uv kuruluyor (Python ve paket yöneticisi, astral.sh)' 'Installing uv (Python and package manager, astral.sh)')
    if ($NoModifyPath) { $env:UV_NO_MODIFY_PATH = '1' }
    try {
        Invoke-RestMethod -Uri 'https://astral.sh/uv/install.ps1' -ErrorAction Stop | Invoke-Expression
    } catch {
        Fail "$(T 'uv indirilemedi' 'Could not download uv'): $($_.Exception.Message)" (T 'İnternet bağlantısını kontrol edin ya da uv''yi elle kurun: https://docs.astral.sh/uv/' 'Check your internet connection or install uv manually: https://docs.astral.sh/uv/')
    }
    $uv = Find-Uv
    if (-not $uv) { Fail (T 'uv kuruldu ama bulunamadı.' 'uv was installed but cannot be found.') (T 'Yeni bir terminal açıp bu betiği tekrar çalıştırın.' 'Open a new terminal and run this script again.') }
}
Ok "uv: $(& $uv --version)"

# Windows çalışan programın dosyalarının değiştirilmesine izin vermez: açık bir gitex (ör. yarıda
# kalmış bir `gitex setup`) varken güncelleme "Erişim engellendi" ile başarısız olur.
$running = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.Name -eq 'gitex.exe' -or ($_.ExecutablePath -and $_.ExecutablePath -like '*\uv\tools\gitex\*')
})
if ($running.Count -gt 0) {
    Write-Host ''
    Write-Host (T '  Açık bir gitex var (ör. yarıda kalmış bir "gitex setup" penceresi).' '  gitex is still running (e.g. an unfinished "gitex setup" window).') -ForegroundColor Yellow
    Write-Host (T '  Açıkken güncelleme yapılamaz:' '  It cannot be updated while running:') -ForegroundColor Yellow
    $running | Where-Object { $_.Name -eq 'gitex.exe' } | ForEach-Object {
        Write-Host "    PID $($_.ProcessId): $($_.CommandLine)" -ForegroundColor DarkGray
    }
    if (-not $Interactive) {
        Fail (T 'Açık gitex pencerelerini kapatın (Ctrl+C) ve kurulumu tekrar çalıştırın.' 'Close the running gitex windows (Ctrl+C) and run the installer again.')
    }
    Write-Host (T '   1) Kapat ve kuruluma devam et  (önerilen)' '   1) Close it and continue  (recommended)')
    Write-Host (T '   2) Vazgeç, kendim kapatacağım' '   2) Cancel, I will close it myself')
    $answer = Read-Host (T 'Seçim [1]' 'Choice [1]')
    if ($answer.Trim() -eq '2') { Fail (T 'Kurulum iptal edildi.' 'Installation cancelled.') (T 'gitex pencerelerini kapatıp tekrar çalıştırın.' 'Close the gitex windows and run it again.') }
    $running | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Milliseconds 700
    Ok (T 'Açık gitex kapatıldı.' 'Closed the running gitex.')
}

Step (T 'Python 3.12 ve gitex kuruluyor (ilk seferde birkaç dakika sürebilir)' 'Installing Python 3.12 and gitex (the first time can take a few minutes)')
& $uv tool install --force --python 3.12 $Root
if ($LASTEXITCODE -ne 0) {
    Fail (T 'gitex kurulamadı.' 'gitex could not be installed.') (T 'Hata "Erişim engellendi" ise açık bir gitex penceresi vardır: kapatıp tekrar çalıştırın. Bu betiği tekrar çalıştırmak güvenlidir.' 'If the error says "Access is denied", a gitex window is still open: close it and run again. Re-running this script is safe.')
}

$binDir = (& $uv tool dir --bin 2>$null | Select-Object -First 1).Trim()
if (-not $NoModifyPath) {
    # uv "zaten PATH'te" gibi bilgileri stderr'e yazar; çıktıyı yutup sonucu kendimiz doğrularız.
    & $uv tool update-shell 2>&1 | Out-Null
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $entries = @($userPath -split ';' | Where-Object { $_ } | ForEach-Object { $_.TrimEnd('\') })
    if ($entries -notcontains $binDir.TrimEnd('\')) {
        $newPath = (@($binDir) + $entries) -join ';'
        [Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
        Ok "$(T "PATH'e eklendi" 'Added to PATH'): $binDir"
    }
}
$env:Path = "$binDir;$env:Path"
$gitex = Join-Path $binDir 'gitex.exe'
if (-not (Test-Path $gitex)) { Fail "$(T 'gitex komutu bulunamadı' 'gitex command not found'): $gitex" }
Ok "$(& $gitex --version) $(T 'kuruldu' 'installed') → $gitex"

# Seçilen dili kaydet; gitex'in bütün mesajları bu dilde olur.
& $gitex config set ui.language $Lang --global 2>&1 | Out-Null

Write-Host ''
if (-not $NoSetup -and $Interactive) {
    Step (T 'Kurulum sihirbazı başlatılıyor (model, API anahtarı, GitLab)' 'Starting the setup wizard (model, API key, GitLab)')
    & $gitex setup --lang $Lang
}

Write-Host ''
Write-Host (T 'Kurulum tamam.' 'Installation complete.') -ForegroundColor Green
Write-Host (T '  Başlamak için bir git deposunda:  gitex ask "Son değişiklikler neler?"' '  To start, inside a git repository:  gitex ask "What changed recently?"')
Write-Host (T '  Ayarlar: gitex setup  ·  Kontrol: gitex doctor  ·  Tüm komutlar: gitex --help' '  Settings: gitex setup  ·  Check: gitex doctor  ·  All commands: gitex --help')

$callerEntries = @($CallerPath -split ';' | Where-Object { $_ } | ForEach-Object { $_.TrimEnd('\') })
if ($NoModifyPath) {
    Write-Host "  $(T 'PATH değiştirilmedi; komut' 'PATH was not changed; command'): $gitex"
} elseif ($callerEntries -notcontains $binDir.TrimEnd('\')) {
    # Bir alt süreç, kendisini başlatan terminalin PATH'ini değiştiremez.
    Write-Host ''
    Write-Host (T '  ÖNEMLİ: Bu terminal penceresi gitex''i henüz tanımıyor.' '  IMPORTANT: this terminal window does not know about gitex yet.') -ForegroundColor Yellow
    Write-Host (T '  Terminali kapatıp yeniden açın — ya da bu pencerede hemen kullanmak için yapıştırın:' '  Close and reopen the terminal — or paste this to use it in this window right away:') -ForegroundColor Yellow
    Write-Host "    PowerShell:  `$env:Path = `"$binDir;`$env:Path`""
    Write-Host "    cmd:         set `"Path=$binDir;%Path%`""
}
