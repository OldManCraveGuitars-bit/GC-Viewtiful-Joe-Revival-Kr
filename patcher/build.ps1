$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$buildRoot = Join-Path $repoRoot 'build'
$distRoot = Join-Path $repoRoot 'dist'
New-Item -ItemType Directory -Path $buildRoot, $distRoot -Force | Out-Null
python -m PyInstaller --noconfirm --clean --onefile --windowed --version-file (Join-Path $PSScriptRoot 'version_info.txt') --name 'Viewtiful-Joe-Revival-Kr-Patcher-v0.9' --add-data "${PSScriptRoot}\resources;resources" --distpath $distRoot --workpath $buildRoot --specpath $buildRoot (Join-Path $PSScriptRoot 'patcher.py')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
