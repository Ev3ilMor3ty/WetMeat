@echo off
setlocal EnableExtensions DisableDelayedExpansion
pushd "%~dp0" || exit /b 1
if exist "WetMeat-Linux.zip" goto existing
if not exist "WetMeat-Linux.zip.part001" (echo Missing part 001 & exit /b 1)
if not exist "WetMeat-Linux.zip.part002" (echo Missing part 002 & exit /b 1)
if not exist "WetMeat-Linux.zip.part003" (echo Missing part 003 & exit /b 1)
if not exist "WetMeat-Linux.zip.part004" (echo Missing part 004 & exit /b 1)
if not exist "WetMeat-Linux.zip.part005" (echo Missing part 005 & exit /b 1)
if not exist "WetMeat-Linux.zip.part006" (echo Missing part 006 & exit /b 1)
if not exist "WetMeat-Linux.zip.part007" (echo Missing part 007 & exit /b 1)
if not exist "WetMeat-Linux.zip.part008" (echo Missing part 008 & exit /b 1)
if not exist "WetMeat-Linux.zip.part009" (echo Missing part 009 & exit /b 1)
if not exist "WetMeat-Linux.zip.part010" (echo Missing part 010 & exit /b 1)
if not exist "WetMeat-Linux.zip.part011" (echo Missing part 011 & exit /b 1)
if not exist "WetMeat-Linux.zip.part012" (echo Missing part 012 & exit /b 1)
if not exist "WetMeat-Linux.zip.part013" (echo Missing part 013 & exit /b 1)
if not exist "WetMeat-Linux.zip.part014" (echo Missing part 014 & exit /b 1)
if not exist "WetMeat-Linux.zip.part015" (echo Missing part 015 & exit /b 1)
if not exist "WetMeat-Linux.zip.part016" (echo Missing part 016 & exit /b 1)
if not exist "WetMeat-Linux.zip.part017" (echo Missing part 017 & exit /b 1)
if not exist "WetMeat-Linux.zip.part018" (echo Missing part 018 & exit /b 1)
if not exist "WetMeat-Linux.zip.part019" (echo Missing part 019 & exit /b 1)
if not exist "WetMeat-Linux.zip.part020" (echo Missing part 020 & exit /b 1)
set "wetmeat_temporary=%TEMP%\wetmeat-join-%RANDOM%-%RANDOM%.zip"
if exist "%wetmeat_temporary%" exit /b 1
copy /b "WetMeat-Linux.zip.part001"+"WetMeat-Linux.zip.part002"+"WetMeat-Linux.zip.part003"+"WetMeat-Linux.zip.part004"+"WetMeat-Linux.zip.part005"+"WetMeat-Linux.zip.part006"+"WetMeat-Linux.zip.part007"+"WetMeat-Linux.zip.part008"+"WetMeat-Linux.zip.part009"+"WetMeat-Linux.zip.part010"+"WetMeat-Linux.zip.part011"+"WetMeat-Linux.zip.part012"+"WetMeat-Linux.zip.part013"+"WetMeat-Linux.zip.part014"+"WetMeat-Linux.zip.part015"+"WetMeat-Linux.zip.part016"+"WetMeat-Linux.zip.part017"+"WetMeat-Linux.zip.part018"+"WetMeat-Linux.zip.part019"+"WetMeat-Linux.zip.part020" "%wetmeat_temporary%" >nul
if errorlevel 1 goto failed
call :verify "%wetmeat_temporary%"
if errorlevel 1 goto failed
move /-y "%wetmeat_temporary%" "WetMeat-Linux.zip" <nul >nul
if errorlevel 1 goto failed
echo Ready: WetMeat-Linux.zip
echo Extract the ZIP and read README.txt inside it.
popd
pause
exit /b 0
:existing
call :verify "WetMeat-Linux.zip"
if errorlevel 1 exit /b 1
echo Ready: WetMeat-Linux.zip
popd
exit /b 0
:verify
certutil -hashfile "%~1" SHA256 2>nul | findstr /i /x /c:"37cb4bb1ee041f8f01fdfd11264df1589d76633e6a70843c0c1c85f80bbfc252" >nul
exit /b %errorlevel%
:failed
if exist "%wetmeat_temporary%" del "%wetmeat_temporary%" >nul 2>nul
echo Joining failed. Check that every numbered part is present and unchanged.
popd
exit /b 1
