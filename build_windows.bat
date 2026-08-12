@echo off
REM ============================================================================
REM  Build "Pokemon PDF Maker.exe" from source.
REM
REM  This wrapper builds on top of Alan Cha's silhouette-card-maker project:
REM  https://github.com/Alan-Cha/silhouette-card-maker  (MIT License)
REM
REM  Requirements: Python 3.11+ and git installed and on PATH.
REM ============================================================================
setlocal
cd /d "%~dp0"

echo.
echo [1/5] Cloning silhouette-card-maker (the engine)...
if not exist "silhouette-card-maker\" (
    git clone --depth 1 https://github.com/Alan-Cha/silhouette-card-maker.git || goto :error
) else (
    echo      already present, skipping.
)

echo.
echo [2/5] Copying the wrapper into the project...
copy /Y "pokemon_pdf_maker.py" "silhouette-card-maker\pokemon_pdf_maker.py" >nul || goto :error

cd silhouette-card-maker

echo.
echo [3/5] Creating virtual environment + installing dependencies...
if not exist ".venv\" python -m venv .venv || goto :error
call .venv\Scripts\python.exe -m pip install --upgrade pip >nul
call .venv\Scripts\python.exe -m pip install -r "..\requirements.txt" pyinstaller || goto :error

echo.
echo [4/5] Building the exe with PyInstaller...
call .venv\Scripts\python.exe -m PyInstaller --noconfirm --onefile --windowed --name "Pokemon PDF Maker" ^
  --add-data "assets;assets" ^
  --add-data "plugins;plugins" ^
  --hidden-import plugins.pokemon.deck_formats ^
  --hidden-import plugins.pokemon.limitless ^
  --collect-all pypdfium2 ^
  pokemon_pdf_maker.py || goto :error

echo.
echo [5/5] Done!  Your app is here:
echo      %cd%\dist\Pokemon PDF Maker.exe
echo.
goto :eof

:error
echo.
echo *** Build failed. See the messages above. ***
exit /b 1
