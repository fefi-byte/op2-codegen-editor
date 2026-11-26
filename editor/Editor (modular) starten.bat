@echo off
REM Startet die modulare Editor-Version (Paket app/). Doppelklick genuegt.
pushd "%~dp0"
python -m app
if errorlevel 1 pause
popd
