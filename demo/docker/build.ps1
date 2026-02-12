# 构建 DeepAnalyze 沙箱镜像
# 用法: cd demo/docker; .\build.ps1

$ErrorActionPreference = "Stop"

$IMAGE_NAME = "deepanalyze-sandbox:latest"
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "=========================================="
Write-Host " 构建 DeepAnalyze 沙箱镜像"
Write-Host " 镜像名称: $IMAGE_NAME"
Write-Host "=========================================="

docker build -t $IMAGE_NAME $SCRIPT_DIR

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ 构建失败" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=========================================="
Write-Host " ✅ 构建完成: $IMAGE_NAME" -ForegroundColor Green
Write-Host "=========================================="
Write-Host ""
Write-Host "验证镜像:"
Write-Host "  docker run --rm $IMAGE_NAME python -c `"import pandas; print('OK')`""
