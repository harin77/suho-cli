@echo off
setlocal enabledelayedexpansion

echo =========================================
echo   SUHO Agent — Windows Installer
echo =========================================
echo.

set "INSTALL_DIR=%USERPROFILE%\.suho\bin"
set "CONFIG_DIR=%USERPROFILE%\.config\suho"

echo [1/3] Creating directories...
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
if not exist "%CONFIG_DIR%" mkdir "%CONFIG_DIR%"

echo [2/3] Installing suho binary...
if exist "suho.exe" (
    copy /Y "suho.exe" "%INSTALL_DIR%\suho.exe" >nul
    echo ✓ Installed suho.exe to %INSTALL_DIR%
) else if exist "target\release\suho.exe" (
    copy /Y "target\release\suho.exe" "%INSTALL_DIR%\suho.exe" >nul
    echo ✓ Installed suho.exe to %INSTALL_DIR%
) else if exist "target\debug\suho.exe" (
    copy /Y "target\debug\suho.exe" "%INSTALL_DIR%\suho.exe" >nul
    echo ✓ Installed suho.exe to %INSTALL_DIR%
) else (
    echo ✗ Error: suho.exe not found in current directory.
    exit /b 1
)

if exist "configs\default.toml" (
    if not exist "%CONFIG_DIR%\config.toml" (
        copy /Y "configs\default.toml" "%CONFIG_DIR%\config.toml" >nul
        echo ✓ Created default config at %CONFIG_DIR%\config.toml
    )
)

echo [3/3] Updating PATH environment variable...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = [Environment]::GetEnvironmentVariable('Path', 'User'); if ($p -notlike '*\.suho\bin*') { [Environment]::SetEnvironmentVariable('Path', $p + ';%INSTALL_DIR%', 'User'); Write-Host '✓ Added %INSTALL_DIR% to User PATH' } else { Write-Host '✓ %INSTALL_DIR% is already in User PATH' }"

echo.
echo =========================================
echo   ✓ SUHO Agent installed successfully!
echo.
echo   To use immediately in THIS window, run:
echo     $env:Path += ";$env:USERPROFILE\.suho\bin"
echo.
echo   Or open a NEW terminal window and type:
echo     suho doctor
echo     suho chat
echo =========================================
echo.
pause
