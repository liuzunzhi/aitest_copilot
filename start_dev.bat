@echo off
setlocal

rem ============================================================
rem  AI 辅助测试平台 · 一键启动开发环境
rem
rem  后端：uvicorn 8000（连开发库 aitest_copilot_v2，.env 自动加载）
rem  前端：vite    5173（代理到 8000）
rem
rem  两个服务各开一个窗口并保持打开（关窗口即停服务）。
rem  本文件存为 GBK 无 BOM —— cmd.exe 按系统 ANSI 代码页(936)解码，
rem  存成 UTF-8 会让文件字节偏移错位、把注释当命令执行。
rem ============================================================

cd /d "%~dp0"

rem ---------- 0. 前置检查 ----------
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo   [x] 没有找到 .venv 虚拟环境！
    echo.
    echo       当前目录：%CD%
    echo       期望位置：%~dp0.venv\Scripts\python.exe
    echo.
    echo       请先安装依赖，在项目根目录执行：
    echo.
    echo           python -m venv .venv
    echo           .venv\Scripts\pip install -r requirements.txt
    echo.
    echo       （若没有 requirements.txt，用 pyproject.toml 装：
    echo           .venv\Scripts\pip install -e .）
    echo.
    pause
    exit /b 1
)

if not exist "web\node_modules" (
    echo.
    echo   [!] web\node_modules 不存在 —— 前端依赖还没装。
    echo.
    echo       脚本仍会启动后端；前端窗口会提示先装依赖。
    echo       请另开一个终端执行：
    echo.
    echo           cd web
    echo           npm install
    echo.
)

rem ---------- 0.5 端口占用检查（只提示，不拦死）----------
call :port_busy 8000
if "%PORT_BUSY%"=="1" (
    echo   [!] 端口 8000 已被占用 —— 后端可能起不来。
    echo       换端口没意义（前端代理写死了 8000），请先关掉占用它的进程。
    echo.
)
call :port_busy 5173
if "%PORT_BUSY%"=="1" (
    echo   [!] 端口 5173 已被占用 —— 前端可能起不来。
    echo.
)

rem ---------- 1. 后端：新窗口跑 uvicorn，窗口保持打开 ----------
echo   [1/2] 启动后端 ... http://127.0.0.1:8000
start "AI 测试平台 - 后端 8000" cmd /k ".venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000"

rem ---------- 2. 前端：新窗口跑 vite，窗口保持打开 ----------
echo   [2/2] 启动前端 ... http://127.0.0.1:5173
start "AI 测试平台 - 前端 5173" cmd /k "cd /d web && npm run dev -- --port 5173 --host 127.0.0.1"

rem ---------- 3. 等 3 秒后自动打开浏览器 ----------
timeout /t 3 /nobreak >nul 2>nul
if errorlevel 1 ping -n 4 127.0.0.1 >nul
start "" http://127.0.0.1:5173

echo.
echo   ------------------------------------------------------------
echo   启动完成，正在打开浏览器：http://127.0.0.1:5173
echo.
echo   账号：admin / Admin12345
echo.
echo   后端窗口：看 uvicorn 日志（关掉即停后端）
echo   前端窗口：看 vite 日志（关掉即停前端）
echo   停止服务：在对应窗口按 Ctrl+C，或直接关闭该窗口
echo   ------------------------------------------------------------
echo.

endlocal
exit /b 0

rem ---------- 子过程：该端口是否已被占用 ----------
:port_busy
set "PORT_BUSY=0"
netstat -ano | findstr ":%1 " | findstr "LISTENING" >nul
if not errorlevel 1 set "PORT_BUSY=1"
exit /b 0
