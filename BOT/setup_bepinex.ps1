<#
setup_bepinex.ps1
==================
Reinstala o BepInEx + copia/recompila o plugin do bot na pasta do jogo.
Roda toda vez que o jogo atualizar/reinstalar e apagar a pasta BepInEx.

Uso:
    powershell -ExecutionPolicy Bypass -File BOT\setup_bepinex.ps1
(ou clique duas vezes em BOT\setup_bepinex.bat)
#>

$ErrorActionPreference = 'Stop'

$GameDir    = 'E:\Games\OnePieceSimulador\Builds_Windows'
$BepInExDir = Join-Path $GameDir 'BepInEx'
$PluginsDir = Join-Path $BepInExDir 'plugins'
$ZipPath    = Join-Path $PSScriptRoot 'vendor\BepInEx_win_x64_5.4.23.2.zip'
$ProjDir    = Join-Path $PSScriptRoot 'OPTCGBotPlugin'
$BuiltDll   = Join-Path $ProjDir 'bin\Debug\net46\OPTCGBotPlugin.dll'

if (-not (Test-Path $GameDir)) {
    Write-Error "Pasta do jogo nao encontrada: $GameDir (o jogo foi instalado em outro lugar?)"
}

if (-not (Test-Path $ZipPath)) {
    Write-Error "Zip do BepInEx nao encontrado em $ZipPath -- baixe de https://github.com/BepInEx/BepInEx/releases/tag/v5.4.23.2 (BepInEx_win_x64_5.4.23.2.zip) e coloque nesse caminho."
}

if (-not (Test-Path $BepInExDir)) {
    Write-Host "[1/3] BepInEx ausente -- extraindo $ZipPath para $GameDir ..."
    Expand-Archive -Path $ZipPath -DestinationPath $GameDir -Force
    Write-Host "      OK."
} else {
    Write-Host "[1/3] BepInEx ja presente em $BepInExDir -- pulando extracao."
}

New-Item -ItemType Directory -Force -Path $PluginsDir | Out-Null

Write-Host "[2/3] Recompilando o plugin (dotnet build) ..."
Push-Location $ProjDir
try {
    dotnet build --nologo -v quiet
    if ($LASTEXITCODE -ne 0) { throw "dotnet build falhou (exit $LASTEXITCODE)" }
} finally {
    Pop-Location
}

# O .csproj ja tem um target pos-build que copia pra $PluginsDir, mas
# copia de novo aqui pra garantir mesmo se o target mudar/falhar silencioso.
Write-Host "[3/3] Copiando OPTCGBotPlugin.dll para $PluginsDir ..."
Copy-Item -Path $BuiltDll -Destination $PluginsDir -Force
Copy-Item -Path ($BuiltDll -replace '\.dll$', '.pdb') -Destination $PluginsDir -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "Pronto. BepInEx + plugin instalados em $GameDir."
Write-Host "Abra o jogo agora -- o LogOutput.log deve aparecer em $BepInExDir\LogOutput.log"
Write-Host "e mostrar 'OPTCGBot v1.1 carregado' perto do inicio."
