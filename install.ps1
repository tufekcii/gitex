<#
.SYNOPSIS
    gitex'i kurar: uv, Python 3.12 ve `gitex` komutu. Sonunda kurulum sihirbazını açar.

.DESCRIPTION
    Repo klonlandıktan sonra tek komut:  .\install.cmd   (ya da: powershell -ExecutionPolicy Bypass -File install.ps1)
    - uv yoksa resmi kurucusuyla kurar (https://docs.astral.sh/uv/)
    - Python 3.12'yi uv indirir; sistemdeki Python'a dokunulmaz
    - gitex'i izole bir ortama kurar ve komutu PATH'e ekler
    Tekrar çalıştırmak güvenlidir; güncelleme için de aynı komut kullanılır.

.PARAMETER NoSetup
    Kurulumdan sonra `gitex setup` sihirbazını başlatma.

.PARAMETER NoModifyPath
    Kullanıcı PATH'ini değiştirme (CI ve test için).

.PARAMETER Uninstall
    gitex'i kaldır (ayarlar ve depo içindeki .gitex/ klasörleri kalır).
#>
[CmdletBinding()]
param(
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

function Step([string]$Message) { Write-Host "==> $Message" -ForegroundColor Cyan }
function Ok([string]$Message) { Write-Host "    $Message" -ForegroundColor Green }
function Fail([string]$Message, [string]$Hint) {
    Write-Host "Hata: $Message" -ForegroundColor Red
    if ($Hint) { Write-Host "İpucu: $Hint" -ForegroundColor DarkGray }
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
    if (-not $uv) { Fail 'uv bulunamadı; gitex zaten kurulu görünmüyor.' }
    Step 'gitex kaldırılıyor'
    & $uv tool uninstall gitex
    Ok 'Kaldırıldı. Anahtar kasasındaki kayıtlar için önce: gitex auth logout'
    exit 0
}

Step 'git kontrol ediliyor'
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Fail 'git bulunamadı.' 'Kurun: https://git-scm.com/download/win  (ya da: winget install Git.Git)'
}
Ok (git --version)

if (-not $uv) {
    Step 'uv kuruluyor (Python ve paket yöneticisi, astral.sh)'
    if ($NoModifyPath) { $env:UV_NO_MODIFY_PATH = '1' }
    try {
        Invoke-RestMethod -Uri 'https://astral.sh/uv/install.ps1' -ErrorAction Stop | Invoke-Expression
    } catch {
        Fail "uv indirilemedi: $($_.Exception.Message)" 'İnternet bağlantısını kontrol edin ya da uv''yi elle kurun: https://docs.astral.sh/uv/'
    }
    $uv = Find-Uv
    if (-not $uv) { Fail 'uv kuruldu ama bulunamadı.' 'Yeni bir terminal açıp bu betiği tekrar çalıştırın.' }
}
Ok "uv: $(& $uv --version)"

Step 'Python 3.12 ve gitex kuruluyor (ilk seferde birkaç dakika sürebilir)'
& $uv tool install --force --python 3.12 $Root
if ($LASTEXITCODE -ne 0) { Fail 'gitex kurulamadı.' 'Yukarıdaki hatayı kontrol edin; bu betiği tekrar çalıştırmak güvenlidir.' }

$binDir = (& $uv tool dir --bin 2>$null | Select-Object -First 1).Trim()
if (-not $NoModifyPath) {
    # uv "zaten PATH'te" gibi bilgileri stderr'e yazar; çıktıyı yutup sonucu kendimiz doğrularız.
    & $uv tool update-shell 2>&1 | Out-Null
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $entries = @($userPath -split ';' | Where-Object { $_ } | ForEach-Object { $_.TrimEnd('\') })
    if ($entries -notcontains $binDir.TrimEnd('\')) {
        $newPath = (@($binDir) + $entries) -join ';'
        [Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
        Ok "PATH'e eklendi: $binDir"
    }
}
$env:Path = "$binDir;$env:Path"
$gitex = Join-Path $binDir 'gitex.exe'
if (-not (Test-Path $gitex)) { Fail "gitex komutu bulunamadı: $gitex" }
Ok "$(& $gitex --version) kuruldu → $gitex"

Write-Host ''
if (-not $NoSetup -and -not [Console]::IsInputRedirected) {
    Step 'Kurulum sihirbazı başlatılıyor (model, API anahtarı, GitLab)'
    & $gitex setup
}

Write-Host ''
Write-Host 'Kurulum tamam.' -ForegroundColor Green
Write-Host '  Başlamak için bir git deposunda:  gitex ask "Son değişiklikler neler?"'
Write-Host '  Ayarlar: gitex setup  ·  Kontrol: gitex doctor  ·  Tüm komutlar: gitex --help'

$callerEntries = @($CallerPath -split ';' | Where-Object { $_ } | ForEach-Object { $_.TrimEnd('\') })
if ($NoModifyPath) {
    Write-Host "  PATH değiştirilmedi; komut: $gitex"
} elseif ($callerEntries -notcontains $binDir.TrimEnd('\')) {
    # Bir alt süreç, kendisini başlatan terminalin PATH'ini değiştiremez.
    Write-Host ''
    Write-Host '  ÖNEMLİ: Bu terminal penceresi gitex''i henüz tanımıyor.' -ForegroundColor Yellow
    Write-Host '  Terminali kapatıp yeniden açın — ya da bu pencerede hemen kullanmak için yapıştırın:' -ForegroundColor Yellow
    Write-Host "    PowerShell:  `$env:Path = `"$binDir;`$env:Path`""
    Write-Host "    cmd:         set `"Path=$binDir;%Path%`""
}
