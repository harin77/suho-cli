@echo off
setlocal enabledelayedexpansion

echo =========================================
echo   SUHO Agent — Windows Installer
echo =========================================
echo.

set "INSTALL_DIR=%USERPROFILE%\.suho\bin"
set "AGENT_DIR=%USERPROFILE%\.suho\python-agent"
set "CONFIG_DIR=%USERPROFILE%\.config\suho"

echo [1/4] Creating installation directories...
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
if not exist "%AGENT_DIR%" mkdir "%AGENT_DIR%"
if not exist "%CONFIG_DIR%" mkdir "%CONFIG_DIR%"

echo [2/4] Installing suho binary and python agent runtime...
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

if exist "python-agent" (
    xcopy /E /I /Y "python-agent" "%AGENT_DIR%" >nul
    echo ✓ Installed python-agent runtime to %AGENT_DIR%
) else (
    echo ✗ Warning: python-agent directory not found in installer package.
)

if exist "configs\default.toml" (
    if not exist "%CONFIG_DIR%\config.toml" (
        copy /Y "configs\default.toml" "%CONFIG_DIR%\config.toml" >nul
        echo ✓ Created default config at %CONFIG_DIR%\config.toml
    )
)

echo [3/4] Installing Python dependencies...
cd /d "%AGENT_DIR%"
where uv >nul 2>&1
if %errorlevel% equ 0 (
    echo Using uv to sync dependencies...
    uv sync
) else (
    where pip >nul 2>&1
    if %errorlevel% equ 0 (
        echo Using pip to install requirements...
        pip install -r requirements.txt
    ) else (
        where pip3 >nul 2>&1
        if %errorlevel% equ 0 (
            echo Using pip3 to install requirements...
            pip3 install -r requirements.txt
        ) else (
            echo ✗ Warning: Neither uv nor pip found in PATH. Make sure Python is installed.
        )
    )
)

echo [4/4] Updating PATH environment variable...
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
