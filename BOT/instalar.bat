@echo off
REM Duplo-clique instala o bot nesta maquina. Ver BOT\instalar.ps1.
powershell -ExecutionPolicy Bypass -File "%~dp0instalar.ps1" %*
pause
