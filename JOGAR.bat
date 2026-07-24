@echo off
REM ============================================================
REM  JOGAR.bat - prepara TUDO para uma partida de teste ao vivo
REM  (branch main -- a branch de trabalho foi mergeada e removida em
REM  24/07, ver HANDOFF; PR #1 fechado como merged)
REM  Duplo-clique -> quando terminar, abra o OPTCGSim e jogue.
REM  IMPORTANTE: feche o JOGO antes de rodar (a DLL e recompilada).
REM ============================================================
cd /d "%~dp0"

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
REM Mata apenas a janela de server aberta por ESTE script anteriormente
taskkill /fi "WINDOWTITLE eq OPTCG Engine Server*" /f >nul 2>&1
start "OPTCG Engine Server" cmd /k "cd /d %~dp0BOT\engine_server && python server.py"

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
