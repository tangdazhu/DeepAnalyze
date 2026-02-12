FROM python:3.12-slim

LABEL maintainer="DeepAnalyze"
LABEL description="DeepAnalyze code execution sandbox"

# 系统依赖（字体、图形渲染）
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-noto-cjk \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 预装数据分析常用库
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

# 设置无界面环境
ENV MPLBACKEND=Agg
ENV MPLCONFIGDIR=/tmp/matplotlib
ENV QT_QPA_PLATFORM=offscreen
ENV PYTHONUNBUFFERED=1
ENV PYTHONIOENCODING=utf-8

# 工作目录
WORKDIR /data

# 非 root 用户执行（安全加固）
RUN useradd -m -s /bin/bash sandbox
USER sandbox
