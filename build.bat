@echo off
echo =============================================
echo  AutoClicker ^& Macro — Power Edition Builder
echo =============================================
echo.

:: Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python not found. Install Python 3.10+ first.
    pause
    exit /b 1
)

:: Install dependencies
echo [1/3] Installing dependencies...
pip install customtkinter pyautogui pyautoit keyboard mouse pywin32 requests pyinstaller --quiet

:: Build
echo [2/3] Building executable...
cd /d "%~dp0src"
pyinstaller --noconfirm --onefile --windowed ^
    --name "AutoClicker&Macro_v2" ^
    --add-data "core_engine.py;." ^
    --add-data "macro_engine.py;." ^
    --hidden-import "pywintypes" ^
    --hidden-import "win32gui" ^
    --hidden-import "win32ui" ^
    --hidden-import "win32con" ^
    --hidden-import "customtkinter" ^
    "AutoClicker&Macro_v2.py"

echo [3/3] Copying assets...
copy /y "..\mouse.ico" "dist\" 2>nul
copy /y "..\gear.png" "dist\" 2>nul
if not exist "dist\Macros" mkdir "dist\Macros"

echo.
echo =============================================
echo  BUILD COMPLETE! Exe at: src\dist\
echo =============================================
pause
