$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Push-Location $PSScriptRoot
try {
    Write-Host '正在准备 Python 环境…'
    uv sync --locked
    if ($LASTEXITCODE -ne 0) { throw 'Python 依赖安装失败' }
    Push-Location (Join-Path $PSScriptRoot 'frontend')
    try {
        npm ci
        if ($LASTEXITCODE -ne 0) { throw '前端依赖安装失败' }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw '前端检查或构建失败' }
    } finally { Pop-Location }
    Write-Host '工作台：http://127.0.0.1:8765；关闭此窗口即可停止服务。'
    uv run litresearch-web
} finally { Pop-Location }
