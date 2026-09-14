@echo off
REM ============================================================
REM  JOGAR.bat - prepara TUDO para uma partida de teste ao vivo
REM  (branch main -- a branch de trabalho foi mergeada e removida em
REM  24/07, ver HANDOFF; PR #1 fechado como merged)
REM  Duplo-clique -> quando terminar, abra o OPTCGSim e jogue.
REM  IMPORTANTE: feche o JOGO antes de rodar (a DLL e recompilada).
REM ============================================================
cd /d "%~dp0"

REM Garante python/git/dotnet no PATH mesmo se o Explorer ainda nao
REM propagou uma variavel de ambiente de usuario recem-criada (achado
REM 31/08/2026: duplo-clique logo apos instalar Python/.NET sem admin
REM pode herdar um PATH desatualizado, e o server sobe em silencio sem
REM escutar a porta 8765 -- o jogo entao so passa o turno).
set "PATH=%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%LOCALAPPDATA%\Programs\nodejs;%LOCALAPPDATA%\Microsoft\dotnet;%PATH%"

REM Pasta do jogo (usada pelo .csproj do plugin E por sim_bridge.py pra
REM achar os .deck) -- mesmo fallback do default do setup_bepinex.ps1.
REM Se OPTCG_GAME_DIR ja estiver setada (variavel de usuario persistente),
REM essa linha nao sobrescreve.
if not defined OPTCG_GAME_DIR set "OPTCG_GAME_DIR=C:\Users\ARTHUR.CUNHA\Desktop\Builds_Windows"

echo === [1/4] Atualizando o codigo (main) ===
git fetch origin
if errorlevel 1 goto :erro
git checkout main
if errorlevel 1 goto :erro
git pull origin main
if errorlevel 1 goto :erro

echo.
echo === [2/4] Recompilando o plugin (BepInEx + DLL do bot) ===
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0BOT\setup_bepinex.ps1"
if errorlevel 1 goto :erro

echo.
echo === [3/4] (Re)subindo o engine server na porta 8765 ===
REM `start` (janela de console nova) e bloqueado por politica corporativa
REM em algumas maquinas (achado 31/08/2026: nao abre nada, nem erro, nem
REM janela -- silencioso). Start-Process do PowerShell com -WindowStyle
REM Hidden nao esbarra nessa restricao (testado e funcionando). Roda em
REM segundo plano, sem janela visivel; log vai pra BOT\engine_server\logs.
REM Mata qualquer instancia anterior do server antes de subir de novo
REM (filtrado por linha de comando -- so mata ESTE server.py, nunca
REM outros processos python.exe que o usuario tenha aberto).
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Get-CimInstance Win32_Process -Filter 'Name=''python.exe''' | Where-Object { $_.CommandLine -like '*engine_server*server.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; Start-Sleep -Milliseconds 500; Start-Process -FilePath 'python' -ArgumentList 'server.py' -WorkingDirectory '%~dp0BOT\engine_server' -WindowStyle Hidden -RedirectStandardOutput '%~dp0BOT\engine_server\logs\server_stdout.log' -RedirectStandardError '%~dp0BOT\engine_server\logs\server_stderr.log'"

REM Espera o server subir de verdade antes de dar "PRONTO" (evita a
REM falsa sensacao de sucesso do bloco anterior, quando nada tinha
REM realmente subido).
echo Aguardando o engine server responder na porta 8765...
set _UP=0
for /L %%i in (1,1,20) do (
  powershell -NoProfile -Command "try { (Invoke-WebRequest -Uri 'http://localhost:8765/docs' -UseBasicParsing -TimeoutSec 1).StatusCode } catch { exit 1 }" >nul 2>&1
  if not errorlevel 1 (
    set _UP=1
    goto :server_ok
  )
  timeout /t 1 /nobreak >nul
)
:server_ok
if "%_UP%"=="1" (
  echo Engine server OK, escutando em http://localhost:8765
) else (
  echo *** O engine server NAO respondeu apos 20s -- veja BOT\engine_server\logs\server_stderr.log ***
)

echo.
echo === [4/4] PRONTO! Abra o OPTCGSim e jogue. ===
echo.
echo  WATCH-LIST desta leva (HANDOFF 299-302):
echo   1. DON!! -N (Katakuri/Pudding/Mamaragan): efeito COMPLETA,
echo      devolvendo DON RESTADO primeiro (e funciona com pouco ativo).
echo   2. Jogo honesto: bot nao ve mais sua mao/vida (comportamento
echo      pode mudar - intencional).
echo   3. Reveals: linha [EngineClient] reveal no LogOutput.log e
echo      evento "reveal" no decision log do server.
echo   4. Arlong/efeitos na SUA mao: bot seleciona as cegas.
echo   5. No fim: [AUTO-COLLECT] LOG SALVO NO BANCO (auto-coleta).
echo.
pause
exit /b 0

:erro
echo.
echo  *** FALHOU - tire um print/copie a mensagem acima e mande pro Claude ***
pause
exit /b 1
