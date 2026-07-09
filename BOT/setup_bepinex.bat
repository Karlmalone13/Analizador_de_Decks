@echo off
REM Duplo-clique pra reinstalar BepInEx + plugin do bot na pasta do jogo.
REM Roda sempre que o jogo atualizar/reinstalar e apagar a pasta BepInEx.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_bepinex.ps1"
pause
