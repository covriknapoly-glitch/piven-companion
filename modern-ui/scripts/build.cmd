@echo off
rem Builds modern-ui\dist for web_companion.pyw with the bundled esbuild (no Node.js needed).
setlocal
cd /d "%~dp0.."
rem Type check first when the portable Node.js (runtime\node) and TypeScript (node_modules) are present.
set NODE=..\runtime\node\node.exe
set TSC=node_modules\typescript\bin\tsc
if exist "%NODE%" if exist "%TSC%" goto typecheck
echo Type check skipped: no runtime\node\node.exe or node_modules\typescript
goto bundle
:typecheck
"%NODE%" "%TSC%" -p . --noEmit
if errorlevel 1 exit /b 1
:bundle
if exist dist rmdir /s /q dist
node_modules\@esbuild\win32-x64\esbuild.exe src\main.tsx --bundle --format=iife --jsx=automatic --minify --target=chrome110 --outdir=dist --entry-names=app --asset-names=assets/[name]-[hash] --loader:.ttf=file --loader:.otf=file --loader:.woff2=file --loader:.png=file --loader:.svg=text --define:process.env.NODE_ENV="\"production\"" --log-level=warning
if errorlevel 1 exit /b 1
copy /y desktop.html dist\index.html >nul
echo Built modern-ui\dist
