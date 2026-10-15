@echo off
setlocal
set "wetmeat_package=%~dp0"
set "wetmeat_install=%LOCALAPPDATA%\WetMeat\1.0-stable"
if not "%~1"=="" set "wetmeat_install=%~1"

if exist "%wetmeat_install%" (
    echo That installation folder already exists:
    echo "%wetmeat_install%"
    echo Choose a new folder to keep your existing installation.
    exit /b 1
)

set "wetmeat_hashfile=%TEMP%\wetmeat-%RANDOM%-%RANDOM%.sha256"
certutil -hashfile "%wetmeat_package%bin\wetmeat-windows-avx2.exe" SHA256 > "%wetmeat_hashfile%" 2>nul
if errorlevel 1 goto hash_failed
findstr /i /x /c:"ba3b51c100e2f7525b61d0a3fed9ffebc587d4b596c4264974cac500dc715282" "%wetmeat_hashfile%" >nul
if errorlevel 1 goto hash_failed
del "%wetmeat_hashfile%" >nul 2>nul

robocopy "%wetmeat_package%." "%wetmeat_install%" /E /XD "%wetmeat_install%" /R:1 /W:1 /NFL /NDL /NJH /NJS
if errorlevel 8 (
    echo The copy failed. You can still use the EXE in the extracted bin folder.
    exit /b 1
)

echo.
echo WetMeat is installed. Add this file as a UCI engine in your chess interface:
echo "%wetmeat_install%\bin\wetmeat-windows-avx2.exe"
echo.
echo Read README.txt for the Cute Chess and Arena setup steps.
if "%~1"=="" pause
exit /b 0

:hash_failed
del "%wetmeat_hashfile%" >nul 2>nul
echo The engine checksum could not be verified. Extract a fresh copy of the ZIP.
exit /b 1
