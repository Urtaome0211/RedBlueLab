@echo off
setlocal
pushd "%~dp0"

set "PYW=.venv\Scripts\pythonw.exe"
set "PY=.venv\Scripts\python.exe"

if exist "%PYW%" (
    start "" "%PYW%" "%~dp0main.py"
    goto :done
)
if exist "%PY%" (
    "%PY%" "%~dp0main.py"
    goto :done
)
where pythonw >nul 2>nul
if not errorlevel 1 (
    start "" pythonw "%~dp0main.py"
    goto :done
)
where python >nul 2>nul
if not errorlevel 1 (
    python "%~dp0main.py"
    goto :done
)
echo [!] Python not found.
echo     Install Python 3.10+ or create the venv first:
echo       python -m venv .venv
echo       .venv\Scripts\python.exe -m pip install -r requirements.txt
pause

:done
popd
endlocal
