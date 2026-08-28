<#
instalar.ps1 -- instala o bot em UMA MAQUINA NOVA, do zero.
=============================================================
Criado 28/08/2026 (bloco 722) a pedido do usuario ("conseguimos gerar um
executavel para eu instalar o bot em outra maquina?").

POR QUE NAO E UM .EXE
---------------------
O bot tem DUAS metades e nenhuma delas vira um executavel unico:
  * o PLUGIN e uma DLL do BepInEx -- por definicao precisa ser DLL, e e
    compilada contra as DLLs do PROPRIO jogo (que mudam de versao e de
    maquina). Um .exe nao seria carregado pelo BepInEx.
  * o MOTOR e Python e precisa do banco de cartas, do parser de efeitos e
    do engine inteiro. Daria pra empacotar com PyInstaller, mas isso tem
    que ser feito NO WINDOWS (nao ha cross-compile).
Este script faz o papel do instalador: acha o jogo, resolve dependencia e
deixa tudo pronto, sem exigir que voce edite caminho nenhum.

USO
---
    powershell -ExecutionPolicy Bypass -File BOT\instalar.ps1
    powershell -ExecutionPolicy Bypass -File BOT\instalar.ps1 -GameDir "D:\Jogos\OnePieceSimulador\Builds_Windows"

O QUE ELE FAZ
-------------
 1. Encontra a pasta do jogo (parametro > variavel de ambiente > busca
    automatica nas bibliotecas Steam e nos discos).
 2. Instala o BepInEx (usa o zip de BOT\vendor\ se existir; senao baixa).
 3. Compila o plugin apontando pro jogo DESTA maquina e copia a DLL.
 4. Cria o ambiente Python e instala as dependencias.
 5. Gera `iniciar_bot.bat` na raiz, que sobe o servidor do motor.
#>
param(
    [string]$GameDir = '',
    [switch]$Rebuild   # forca recompilar mesmo havendo DLL pronta em BOT\dist\
)
$ErrorActionPreference = 'Stop'
$Raiz = Split-Path -Parent $PSScriptRoot
$BepZipVer = '5.4.23.2'

function Passo($n, $txt) { Write-Host "`n[$n] $txt" -ForegroundColor Cyan }

# ── 1. achar o jogo ────────────────────────────────────────────────────
Passo '1/5' 'Procurando a instalacao do OPTCGSim...'
if (-not $GameDir) { $GameDir = $env:OPTCG_GAME_DIR }
if (-not $GameDir) {
    $palpites = @()
    # bibliotecas Steam declaradas no libraryfolders.vdf
    foreach ($steam in @("$env:ProgramFiles(x86)\Steam", "$env:ProgramFiles\Steam", 'C:\Steam')) {
        $vdf = Join-Path $steam 'steamapps\libraryfolders.vdf'
        if (Test-Path $vdf) {
            foreach ($m in ([regex]'"path"\s+"([^"]+)"').Matches((Get-Content $vdf -Raw))) {
                $palpites += Join-Path ($m.Groups[1].Value -replace '\\\\', '\') 'steamapps\common'
            }
        }
    }
    foreach ($d in (Get-PSDrive -PSProvider FileSystem).Root) {
        $palpites += @("${d}Games", "${d}Jogos", "${d}SteamLibrary\steamapps\common", $d)
    }
    foreach ($base in ($palpites | Select-Object -Unique)) {
        if (-not (Test-Path $base)) { continue }
        $achado = Get-ChildItem -Path $base -Filter 'OPTCGSim_Data' -Directory -Recurse `
                    -Depth 3 -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($achado) { $GameDir = $achado.Parent.FullName; break }
    }
}
if (-not $GameDir -or -not (Test-Path (Join-Path $GameDir 'OPTCGSim_Data'))) {
    Write-Host ''
    Write-Host 'Nao encontrei o jogo automaticamente.' -ForegroundColor Yellow
    Write-Host 'Rode de novo apontando a pasta que contem OPTCGSim_Data, por exemplo:'
    Write-Host '  powershell -ExecutionPolicy Bypass -File BOT\instalar.ps1 -GameDir "D:\Jogos\OnePieceSimulador\Builds_Windows"'
    exit 1
}
Write-Host "    jogo: $GameDir" -ForegroundColor Green
$env:OPTCG_GAME_DIR = $GameDir

# ── 2. BepInEx ─────────────────────────────────────────────────────────
Passo '2/5' 'BepInEx...'
$BepDir = Join-Path $GameDir 'BepInEx'
if (Test-Path (Join-Path $BepDir 'core\BepInEx.dll')) {
    Write-Host '    ja instalado' -ForegroundColor Green
} else {
    $zip = Join-Path $PSScriptRoot "vendor\BepInEx_win_x64_$BepZipVer.zip"
    if (-not (Test-Path $zip)) {
        New-Item -ItemType Directory -Force -Path (Split-Path $zip) | Out-Null
        $url = "https://github.com/BepInEx/BepInEx/releases/download/v$BepZipVer/BepInEx_win_x64_$BepZipVer.zip"
        Write-Host "    baixando $url"
        Invoke-WebRequest -Uri $url -OutFile $zip
    }
    Expand-Archive -Path $zip -DestinationPath $GameDir -Force
    Write-Host '    instalado -- ABRA O JOGO UMA VEZ e feche, pra ele gerar as pastas' -ForegroundColor Yellow
}

# ── 3. plugin ──────────────────────────────────────────────────────────
Passo '3/5' 'Plugin...'
$PluginsDir = Join-Path $BepDir 'plugins'
$DllPronta  = Join-Path $PSScriptRoot 'dist\OPTCGBotPlugin.dll'

# CAMINHO RAPIDO (bloco 727, pedido do usuario: "deixar ele em Dll para
# podermos instalar em varios computadores"): se existe DLL pre-compilada
# em BOT\dist\, so copia -- a maquina nova NAO precisa de .NET SDK.
# Compilar so e necessario pra GERAR a DLL (uma vez, numa maquina) ou
# quando o jogo atualiza e muda as DLLs contra as quais ela foi ligada.
if ((Test-Path $DllPronta) -and (-not $Rebuild)) {
    New-Item -ItemType Directory -Force -Path $PluginsDir | Out-Null
    Copy-Item $DllPronta -Destination $PluginsDir -Force
    Write-Host "    DLL pre-compilada copiada de BOT\dist\ (sem precisar de .NET)" -ForegroundColor Green
    Write-Host "    se o bot nao reagir no jogo, rode com -Rebuild (o jogo pode ter atualizado)" -ForegroundColor DarkGray
    $PulaBuild = $true
} else {
    $PulaBuild = $false
}

if (-not $PulaBuild) {
if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) {
    Write-Host '    .NET SDK ausente -- instale de https://dotnet.microsoft.com/download' -ForegroundColor Red
    Write-Host '    (necessario porque o plugin e compilado contra as DLLs DESTE jogo)' -ForegroundColor Red
    Write-Host '    OU peca a quem ja compilou pra commitar BOT\dist\OPTCGBotPlugin.dll' -ForegroundColor Yellow
    exit 1
}
Push-Location (Join-Path $PSScriptRoot 'OPTCGBotPlugin')
try {
    dotnet build -c Debug -p:GameDir="$GameDir"
    if ($LASTEXITCODE -ne 0) { throw 'falha ao compilar o plugin' }
} finally { Pop-Location }
Write-Host "    DLL copiada para $PluginsDir" -ForegroundColor Green

# Guarda a DLL recem-compilada em BOT\dist\ pra OUTRAS maquinas nao
# precisarem de .NET SDK -- e o que torna o bot instalavel em varios PCs.
$dist = Join-Path $PSScriptRoot 'dist'
New-Item -ItemType Directory -Force -Path $dist | Out-Null
$built = Join-Path $PSScriptRoot 'OPTCGBotPlugin\bin\Debug\net46\OPTCGBotPlugin.dll'
if (Test-Path $built) {
    Copy-Item $built -Destination $dist -Force
    Write-Host "    copia guardada em BOT\dist\ -- commite esse arquivo pra instalar em outros PCs" -ForegroundColor Cyan
}
}

# ── 4. Python ──────────────────────────────────────────────────────────
Passo '4/5' 'Ambiente Python...'
$py = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $py) {
    Write-Host '    Python ausente -- instale 3.10+ de https://python.org (marque "Add to PATH")' -ForegroundColor Red
    exit 1
}
$venv = Join-Path $Raiz '.venv'
if (-not (Test-Path $venv)) { python -m venv $venv }
& (Join-Path $venv 'Scripts\python.exe') -m pip install --quiet --upgrade pip
& (Join-Path $venv 'Scripts\python.exe') -m pip install --quiet -r (Join-Path $Raiz 'scriptis_da_ia\requirements.txt')
& (Join-Path $venv 'Scripts\python.exe') -m pip install --quiet pandas
Write-Host '    dependencias instaladas' -ForegroundColor Green

# ── 5. atalho ──────────────────────────────────────────────────────────
Passo '5/5' 'Criando iniciar_bot.bat...'
@"
@echo off
REM Gerado por BOT\instalar.ps1 -- sobe o servidor do motor.
REM Abra o OPTCGSim DEPOIS que este terminal disser que esta ouvindo.
set OPTCG_GAME_DIR=$GameDir
cd /d "$Raiz"
".venv\Scripts\python.exe" BOT\engine_server\server.py
pause
"@ | Set-Content -Encoding ASCII (Join-Path $Raiz 'iniciar_bot.bat')

Write-Host "`nPRONTO." -ForegroundColor Green
Write-Host "  1. clique em iniciar_bot.bat (sobe o motor em localhost:8765)"
Write-Host "  2. abra o OPTCGSim e va em Solo vs Self"
Write-Host "  3. o bot joga o lado de BAIXO"
Write-Host "`n  Se o jogo atualizar e o bot parar: rode este instalador de novo."
