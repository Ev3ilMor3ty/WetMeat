@echo off
setlocal EnableExtensions DisableDelayedExpansion
pushd "%~dp0" || exit /b 1
if exist "WetMeat-Windows.zip" goto existing
if not exist "WetMeat-Windows.zip.part001" (echo Missing part 001 & exit /b 1)
if not exist "WetMeat-Windows.zip.part002" (echo Missing part 002 & exit /b 1)
if not exist "WetMeat-Windows.zip.part003" (echo Missing part 003 & exit /b 1)
if not exist "WetMeat-Windows.zip.part004" (echo Missing part 004 & exit /b 1)
if not exist "WetMeat-Windows.zip.part005" (echo Missing part 005 & exit /b 1)
if not exist "WetMeat-Windows.zip.part006" (echo Missing part 006 & exit /b 1)
if not exist "WetMeat-Windows.zip.part007" (echo Missing part 007 & exit /b 1)
if not exist "WetMeat-Windows.zip.part008" (echo Missing part 008 & exit /b 1)
if not exist "WetMeat-Windows.zip.part009" (echo Missing part 009 & exit /b 1)
if not exist "WetMeat-Windows.zip.part010" (echo Missing part 010 & exit /b 1)
set "wetmeat_temporary=%TEMP%\wetmeat-join-%RANDOM%-%RANDOM%.zip"
if exist "%wetmeat_temporary%" exit /b 1
copy /b "WetMeat-Windows.zip.part001"+"WetMeat-Windows.zip.part002"+"WetMeat-Windows.zip.part003"+"WetMeat-Windows.zip.part004"+"WetMeat-Windows.zip.part005"+"WetMeat-Windows.zip.part006"+"WetMeat-Windows.zip.part007"+"WetMeat-Windows.zip.part008"+"WetMeat-Windows.zip.part009"+"WetMeat-Windows.zip.part010" "%wetmeat_temporary%" >nul
if errorlevel 1 goto failed
call :verify "%wetmeat_temporary%"
if errorlevel 1 goto failed
move /-y "%wetmeat_temporary%" "WetMeat-Windows.zip" <nul >nul
if errorlevel 1 goto failed
echo Ready: WetMeat-Windows.zip
echo Extract the ZIP and read README.txt inside it.
popd
pause
exit /b 0
:existing
call :verify "WetMeat-Windows.zip"
if errorlevel 1 exit /b 1
echo Ready: WetMeat-Windows.zip
popd
exit /b 0
:verify
certutil -hashfile "%~1" SHA256 2>nul | findstr /i /x /c:"9970fac79458cac93ddc8974d58571606a0d0f7419c9cbf1136a98e8efd6ce53" >nul
exit /b %errorlevel%
:failed
if exist "%wetmeat_temporary%" del "%wetmeat_temporary%" >nul 2>nul
echo Joining failed. Check that every numbered part is present and unchanged.
popd
exit /b 1
