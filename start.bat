@echo off
chcp 65001 >nul
title SandboxQQ

echo [SandboxQQ] 正在检查依赖...
python -m pip install -r "%~dp0requirements.txt" -q
if errorlevel 1 (
    echo [SandboxQQ] 依赖安装失败，请手动执行: pip install -r requirements.txt
    pause
    exit /b 1
)

python "%~dp0main.py"
if errorlevel 1 (
    echo [SandboxQQ] 程序退出，错误码: %errorlevel%
    pause
)
