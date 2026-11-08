@echo off
setlocal
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment not found. Run scripts\setup.cmd dev first.
    exit /b 1
)

if not exist "test-results" mkdir "test-results"
set "TEST_TEMP=%CD%\.test-tmp\pytest-%RANDOM%-%RANDOM%"
if not exist "%TEST_TEMP%" mkdir "%TEST_TEMP%"
set "TEMP=%TEST_TEMP%"
set "TMP=%TEMP%"
".venv\Scripts\python.exe" -m pytest --basetemp "%TEMP%" %*
if errorlevel 1 exit /b %errorlevel%

echo JUnit report: %CD%\test-results\junit.xml
echo Coverage XML: %CD%\test-results\coverage.xml
echo Coverage HTML: %CD%\test-results\coverage-html\index.html
