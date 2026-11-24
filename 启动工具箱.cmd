@echo off
setlocal
cd /d "%~dp0"
if not exist "launch.pyw" goto missing
for %%P in (pythonw.exe pyw.exe) do if not "%%~$PATH:P"=="" (
  start "" "%%~$PATH:P" -B "launch.pyw"
  exit /b
)
echo Pythonw not found. Please install Python 3 and add it to PATH.
pause
exit /b 1
:missing
echo Keep this launcher in the folder containing launch.pyw.
pause
exit /b 1
