@echo off
setlocal enabledelayedexpansion

echo =========================================
echo   SUHO Agent — Windows Uninstaller
echo =========================================
echo.

set "SUHO_DIR=%USERPROFILE%\.suho"
set "BIN_DIR=%USERPROFILE%\.suho\bin"
set "CONFIG_DIR=%USERPROFILE%\.config\suho"

echo [1/3] Removing binaries and agent runtime...
if exist "%SUHO_DIR%" (
    rmdir /S /Q "%SUHO_DIR%" 2>nul
    echo ✓ Removed %SUHO_DIR%
) else (
    echo ✓ %SUHO_DIR% is already removed.
)

echo [2/3] Removing SUHO from User PATH environment variable...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = [Environment]::GetEnvironmentVariable('Path', 'User'); if ($p -like '*\.suho\bin*') { $newPath = ($p -split ';' | Where-Object { $_ -notlike '*\.suho\bin*' }) -join ';'; [Environment]::SetEnvironmentVariable('Path', $newPath, 'User'); Write-Host '✓ Removed \.suho\bin from User PATH' } else { Write-Host '✓ \.suho\bin is not in User PATH' }"

echo [3/3] Configuration files...
set /p REMOVE_CONFIG="Do you also want to remove configuration files in %CONFIG_DIR%? (y/n) [default: n]: "
if /i "%REMOVE_CONFIG%"=="y" (
    if exist "%CONFIG_DIR%" (
        rmdir /S /Q "%CONFIG_DIR%" 2>nul
        echo ✓ Removed configuration directory %CONFIG_DIR%
    )
) else (
    echo ✓ Kept configuration directory %CONFIG_DIR%
)

echo.
echo =========================================
echo   ✓ SUHO Agent uninstalled successfully!
echo =========================================
echo.
pause
