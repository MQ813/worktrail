param([string]$Output = 'dist')
$ErrorActionPreference = 'Stop'
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --windowed --onedir --name WorkTrail --icon assets/WorkTrail.ico --distpath $Output --paths src --collect-all webview --collect-data mail_jira_assistant --collect-data tzdata --hidden-import win32com.client --hidden-import pythoncom --hidden-import uvicorn.logging --hidden-import uvicorn.loops.auto --hidden-import uvicorn.protocols.http.h11_impl --hidden-import uvicorn.protocols.websockets.auto --hidden-import uvicorn.lifespan.on scripts/desktop_entry.py
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }
Copy-Item README.md -Destination (Join-Path $Output 'WorkTrail')
$docsTarget = Join-Path $Output 'WorkTrail\docs'
New-Item -ItemType Directory -Path $docsTarget -Force | Out-Null
Get-ChildItem -LiteralPath docs -Filter '*.md' | Copy-Item -Destination $docsTarget
& .\.venv\Scripts\python.exe -m pip freeze --exclude-editable | Set-Content -Encoding utf8 requirements-windows.lock
