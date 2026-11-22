# 打包桌面应用，产物：
#   dist\RedBlueLab\RedBlueLab.exe       文件夹版（推荐：不写临时目录，启动快，最稳）
#   dist\RedBlueLab-onefile.exe          单文件版（首次启动解压到 %LOCALAPPDATA%\RedBlueLab\tmp）
# 用法：pwsh -File build_exe.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = if (Test-Path ".\.venv\Scripts\python.exe") { ".\.venv\Scripts\python.exe" } else { "python" }
$common = @(
    "--noconfirm", "--clean", "--noconsole",
    "--icon", "assets\app.ico",
    "--add-data", "data\ssq_history.csv;seed",
    "--add-data", "data\raw;seed\raw",
    "--add-data", "data\dlt_history.csv;seed",
    "--add-data", "data\dlt_raw;seed\dlt_raw",
    "--add-data", "data\kl8_history.csv;seed",
    "--add-data", "data\fc3d_history.csv;seed",
    "--add-data", "data\qlc_history.csv;seed",
    "--add-data", "data\qxc_history.csv;seed",
    "--add-data", "data\pl3_history.csv;seed",
    "--add-data", "data\pl5_history.csv;seed",
    "--add-data", "data\kl8_raw;seed\kl8_raw",
    "--add-data", "data\fc3d_raw;seed\fc3d_raw",
    "--add-data", "data\qlc_raw;seed\qlc_raw",
    "--add-data", "data\qxc_raw;seed\qxc_raw",
    "--add-data", "data\pl3_raw;seed\pl3_raw",
    "--add-data", "data\pl5_raw;seed\pl5_raw",
    "--hidden-import", "pyqtgraph",
    "--hidden-import", "pyqtgraph.graphicsItems",
    "--exclude-module", "PySide6.QtWebEngineCore",
    "--exclude-module", "PySide6.QtWebEngineWidgets",
    "--exclude-module", "PySide6.Qt3DCore",
    "--exclude-module", "PySide6.QtQuick",
    "--exclude-module", "tkinter",
    "--exclude-module", "matplotlib"
)

Write-Host "[1/4] 同步数据集..." -ForegroundColor Cyan
& $python build_dataset.py
& $python -m dlt.build
& $python -m games.build qlc
& $python -m games.build kl8
& $python -m games.build fc3d
& $python -m games.build qxc
& $python -m games.build pl3
& $python -m games.build pl5

if (-not (Test-Path "assets\app.ico")) {
    Write-Host "生成图标..." -ForegroundColor Cyan
    & $python tools\make_icon.py
}

Write-Host "[2/4] 清理旧产物..." -ForegroundColor Cyan
foreach ($d in "build", "build-onefile", "dist") {
    if (Test-Path $d) { Remove-Item -Recurse -Force $d }
}

Write-Host "[3/4] 打包文件夹版 dist\RedBlueLab ..." -ForegroundColor Cyan
& $python -m PyInstaller @common --onedir --name RedBlueLab --workpath build --distpath dist main.py

Write-Host "[4/4] 打包单文件版 dist\RedBlueLab-onefile.exe ..." -ForegroundColor Cyan
& $python -m PyInstaller @common --onefile --runtime-tmpdir "%LOCALAPPDATA%\RedBlueLab\tmp" --name RedBlueLab-onefile --workpath build-onefile --distpath dist main.py

Write-Host "[5/5] 生成单文件版启动脚本 ..." -ForegroundColor Cyan
$launcher = @'
@echo off
rem 单文件版每次启动都要把自身解压到临时目录，某些机器 %TEMP% 不可用时会报
rem "Could not create temporary directory!"，这里把临时目录固定到脚本旁边。
setlocal
set "TEMP=%~dp0runtime_tmp"
set "TMP=%~dp0runtime_tmp"
if not exist "%TEMP%" mkdir "%TEMP%"
start "" "%~dp0RedBlueLab-onefile.exe" %*
'@
[IO.File]::WriteAllText((Join-Path $PWD "dist\单文件版启动.bat"), ($launcher -replace "`r?`n", "`r`n"), [Text.Encoding]::ASCII)

$ok = $true
if (Test-Path "dist\RedBlueLab\RedBlueLab.exe") {
    $mb = (Get-ChildItem "dist\RedBlueLab" -Recurse | Measure-Object Length -Sum).Sum / 1MB
    Write-Host ("完成：dist\RedBlueLab\RedBlueLab.exe (文件夹共 {0:N1} MB)" -f $mb) -ForegroundColor Green
} else {
    Write-Host "缺少 dist\RedBlueLab\RedBlueLab.exe" -ForegroundColor Red; $ok = $false
}
if (Test-Path "dist\RedBlueLab-onefile.exe") {
    $mb = (Get-Item "dist\RedBlueLab-onefile.exe").Length / 1MB
    Write-Host ("完成：dist\RedBlueLab-onefile.exe ({0:N1} MB)" -f $mb) -ForegroundColor Green
} else {
    Write-Host "缺少 dist\RedBlueLab-onefile.exe" -ForegroundColor Red; $ok = $false
}
if (Test-Path "docs\dist_readme.txt") {
    Copy-Item "docs\dist_readme.txt" "dist\使用说明.txt" -Force
    Write-Host "完成：dist\使用说明.txt" -ForegroundColor Green
}
if (-not $ok) { throw "打包失败" }
