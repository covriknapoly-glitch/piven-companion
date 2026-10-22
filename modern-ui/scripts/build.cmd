@echo off
rem Builds modern-ui\dist for web_companion.pyw with the bundled esbuild (no Node.js needed).
setlocal
cd /d "%~dp0.."
if exist dist rmdir /s /q dist
node_modules\@esbuild\win32-x64\esbuild.exe src\main.tsx --bundle --format=iife --jsx=automatic --minify --target=chrome110 --outdir=dist --entry-names=app --asset-names=assets/[name]-[hash] --loader:.ttf=file --loader:.png=file --define:process.env.NODE_ENV="\"production\"" --log-level=warning
if errorlevel 1 exit /b 1
copy /y desktop.html dist\index.html >nul
echo Built modern-ui\dist
