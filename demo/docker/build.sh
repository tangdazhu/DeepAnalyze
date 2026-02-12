#!/usr/bin/env bash
# 构建 DeepAnalyze 沙箱镜像
# 用法: cd demo/docker && bash build.sh

set -euo pipefail

IMAGE_NAME="deepanalyze-sandbox:latest"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=========================================="
echo " 构建 DeepAnalyze 沙箱镜像"
echo " 镜像名称: ${IMAGE_NAME}"
echo "=========================================="

docker build -t "${IMAGE_NAME}" "${SCRIPT_DIR}"

echo ""
echo "=========================================="
echo " ✅ 构建完成: ${IMAGE_NAME}"
echo "=========================================="
echo ""
echo "验证镜像:"
echo "  docker run --rm ${IMAGE_NAME} python -c \"import pandas; print('OK')\""
