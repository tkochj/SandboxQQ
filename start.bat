@echo off
chcp 65001 >nul
title SandboxQQ

if not exist "%~dp0.deps_ok" (
    echo [SandboxQQ] Installing dependencies...
    pip install -r "%~dp0requirements.txt" -q
    if errorlevel 1 (
        echo [SandboxQQ] Dependency install failed - check network
        pause
        exit /b 1
    )
    type nul > "%~dp0.deps_ok"
)

python "%~dp0main.py"
if errorlevel 1 (
    echo [SandboxQQ] Exited with code %errorlevel%
    pause
)
