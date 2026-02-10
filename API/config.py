"""
Configuration module for DeepAnalyze API Server
Contains all configuration constants and environment setup
"""

import os

# Environment setup
os.environ.setdefault("MPLBACKEND", "Agg")

# API Configuration
API_BASE = "http://localhost:8000/v1"  # vLLM API endpoint
MODEL_PATH = "DeepAnalyze-8B"
WORKSPACE_BASE_DIR = "workspace"
HTTP_SERVER_PORT = 8100
HTTP_SERVER_BASE = f"http://localhost:{HTTP_SERVER_PORT}"

# API Server Configuration
API_HOST = "0.0.0.0"
API_PORT = 8200
API_TITLE = "DeepAnalyze OpenAI-Compatible API"
API_VERSION = "1.0.0"

# Thread cleanup configuration
CLEANUP_TIMEOUT_HOURS = 12
CLEANUP_INTERVAL_MINUTES = 30

# Code execution configuration
CODE_EXECUTION_TIMEOUT = 120
MAX_NEW_TOKENS = 32768
MAX_PROMPT_CHARS = 16000

# File handling configuration
FILE_STORAGE_DIR = os.path.join(WORKSPACE_BASE_DIR, "_files")
VALID_FILE_PURPOSES = ["fine-tune", "answers", "file-extract", "assistants"]

# Model configuration
DEFAULT_TEMPERATURE = 0.4
DEFAULT_MODEL = "DeepAnalyze-8B"

# Thinking 模式开关（适用于 Qwen3 等支持 thinking 的模型）
# True  = 启用深度推理（更慢但推理能力更强，适合复杂数学/逻辑任务）
# False = 禁用 thinking（更快，适合代码生成和数据分析任务）
ENABLE_THINKING = False

# Stop token IDs for DeepAnalyze model
STOP_TOKEN_IDS = [151676, 151645]

# Supported tools
SUPPORTED_TOOLS = ["code_interpreter"]
