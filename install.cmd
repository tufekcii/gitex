@echo off
rem gitex kurulumu (Windows). Cift tiklayin ya da terminalde: install.cmd
rem Secenekler install.ps1'e aynen gecer: -NoSetup, -NoModifyPath, -Uninstall
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
set EXITCODE=%ERRORLEVEL%
rem Cift tiklamayla acildiysa pencere hemen kapanmasin.
echo %CMDCMDLINE% | find /i "%~nx0" >nul && (echo. & pause)
exit /b %EXITCODE%
