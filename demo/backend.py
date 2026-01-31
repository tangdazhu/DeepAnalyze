import contextlib
import http.server
import io
import json
import logging
import os
import re
import shutil
import socketserver
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import threading
from collections import defaultdict
from functools import partial
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

import httpx
import openai
import requests
import uvicorn
from fastapi import Body, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from copy import deepcopy

PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_DIR = PROJECT_ROOT / "API"
for path_candidate in (str(PROJECT_ROOT), str(API_DIR)):
    if path_candidate not in sys.path:
        sys.path.insert(0, path_candidate)

import config as api_config
from backend_helpers import (
    README_SECTION_HEADERS,
    README_BULLET_PATTERN,
    build_filesystem_summary_template,
    build_html_report_template,
    validate_readme_document,
)

os.environ.setdefault("MPLBACKEND", "Agg")

# 配置物理日志文件
LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "backend.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

logger.info(f"[启动] 日志文件: {LOG_DIR / 'backend.log'}")


class WorkspaceAccessFilter(logging.Filter):
    """屏蔽 uvicorn access log 中针对 workspace 文件树接口的噪声日志。"""

    TARGETS = ("GET /workspace/files", "GET /workspace/tree")

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            message = record.msg if isinstance(record.msg, str) else ""
        content = message or ""
        return not any(target in content for target in self.TARGETS)


logging.getLogger("uvicorn.access").addFilter(WorkspaceAccessFilter())


# 加载 COMMON_WORDS 配置
def load_common_words_config():
    """从配置文件加载 COMMON_WORDS 集合

    注意: 此函数必须成功加载配置文件,否则抛出异常终止程序。
    不提供后备集合,避免因配置缺失导致的潜在bug。
    """
    config_path = Path(__file__).resolve().parent / "config" / "common_words.json"

    if not config_path.exists():
        error_msg = (
            f"❌ 配置文件不存在: {config_path}\n"
            f"请确保 config/common_words.json 文件存在。\n"
            f"参考文档: config/README.md"
        )
        logger.error(f"[配置] {error_msg}")
        raise FileNotFoundError(error_msg)

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        error_msg = (
            f"❌ 配置文件JSON格式错误: {config_path}\n"
            f"错误详情: {e}\n"
            f"请检查JSON语法是否正确。"
        )
        logger.error(f"[配置] {error_msg}")
        raise ValueError(error_msg) from e
    except Exception as e:
        error_msg = f"❌ 读取配置文件失败: {config_path}\n错误: {e}"
        logger.error(f"[配置] {error_msg}")
        raise RuntimeError(error_msg) from e

    # 合并所有分类的词汇
    words = set()
    categories = config.get("categories", {})

    if not categories:
        error_msg = (
            f"❌ 配置文件中缺少 'categories' 字段或为空: {config_path}\n"
            f"请参考 config/README.md 正确配置。"
        )
        logger.error(f"[配置] {error_msg}")
        raise ValueError(error_msg)

    for category_name, category_words in categories.items():
        if isinstance(category_words, list):
            words.update(category_words)
        else:
            logger.warning(f"[配置] 分类 '{category_name}' 的值不是列表,已跳过")

    if not words:
        error_msg = (
            f"❌ 配置文件中没有加载到任何词汇: {config_path}\n"
            f"请检查 categories 中是否有有效的词汇列表。"
        )
        logger.error(f"[配置] {error_msg}")
        raise ValueError(error_msg)

    logger.info(
        f"[配置] ✅ 已加载 {len(words)} 个常见词汇 (来自 {len(categories)} 个分类)"
    )
    return words


# 全局加载 COMMON_WORDS
COMMON_WORDS_GLOBAL = load_common_words_config()


def load_round_io_rules_config() -> dict[int, dict[str, Any]]:
    """加载多轮输入/输出校验规则."""
    config_path = Path(__file__).resolve().parent / "config" / "round_io_rules.json"
    if not config_path.exists():
        error_msg = (
            f"❌ 配置文件不存在: {config_path}\n"
            "请创建 round_io_rules.json（参考 config/README.md）。"
        )
        logger.error(f"[配置] {error_msg}")
        raise FileNotFoundError(error_msg)

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        error_msg = (
            f"❌ round_io_rules.json JSON 格式错误: {config_path}\n" f"错误详情: {e}"
        )
        logger.error(f"[配置] {error_msg}")
        raise ValueError(error_msg) from e
    except Exception as e:
        error_msg = f"❌ 读取 round_io_rules.json 失败: {config_path}\n错误: {e}"
        logger.error(f"[配置] {error_msg}")
        raise RuntimeError(error_msg) from e

    rounds = config.get("rounds")
    if not isinstance(rounds, list) or not rounds:
        error_msg = (
            f"❌ round_io_rules.json 中缺少有效的 rounds 列表: {config_path}\n"
            "请参照文档提供每一轮的规则。"
        )
        logger.error(f"[配置] {error_msg}")
        raise ValueError(error_msg)

    rules: dict[int, dict[str, Any]] = {}
    for entry in rounds:
        round_no = entry.get("round")
        if not isinstance(round_no, int):
            raise ValueError(
                f"round_io_rules.json 中存在无效轮次: {entry}. round 字段必须是整数。"
            )
        if round_no in rules:
            raise ValueError(
                f"round_io_rules.json 中检测到重复轮次: {round_no}. 每个 round 只能配置一次。"
            )
        rules[round_no] = entry

    logger.info(f"[配置] ✅ 已加载 round_io_rules: 共 {len(rules)} 条规则")
    return rules


ROUND_IO_RULES = load_round_io_rules_config()


def get_round_rule(round_no: int) -> Optional[dict[str, Any]]:
    """返回指定轮次的规则（若未配置则返回 None）。"""
    return ROUND_IO_RULES.get(round_no)


def describe_round(rule: dict[str, Any]) -> str:
    mode = (rule.get("mode") or "").lower()
    input_cfg = rule.get("input") or {}
    outputs = rule.get("outputs") or []
    output_names = " + ".join(
        out.get("filename", "目标文件") for out in outputs if out.get("filename")
    )
    output_names = output_names or "指定输出"

    if mode == "csv_analysis":
        csv_name = input_cfg.get("filename", "指定 CSV")
        return f"分析 {csv_name} → 生成 {output_names}"
    if mode == "sqlite_join":
        tables = ", ".join(input_cfg.get("tables", [])) or "多张表"
        return f"SQLite 多表关联（{tables}）→ 生成 {output_names}"
    if mode == "filesystem_summary":
        path = input_cfg.get("path", "generated/ 目录")
        return f"遍历 {path} → 生成 {output_names}"
    if mode == "html_report":
        path = input_cfg.get("path", "generated/ 目录")
        return f"遍历 {path} → 生成 HTML 报告（{output_names}）"
    return f"{mode or '该'} 轮任务 → 生成 {output_names}"


def guidance_for_rule(rule: dict[str, Any]) -> str:
    mode = (rule.get("mode") or "").lower()
    custom = rule.get("guidance")
    if custom:
        if mode == "filesystem_summary":
            return custom + "\n\n" + build_filesystem_summary_template()
        if mode == "html_report":
            html_name = "multi_table_analysis.html"
            html_files = round_expected_filenames_by_type(rule, "html")
            if html_files:
                html_name = html_files[0]
            return custom + "\n\n" + build_html_report_template(html_name)
        return custom
    if mode == "csv_analysis":
        return (
            "直接输出 <Analyze> 和 <Code>，使用 pandas 读取配置指定的 CSV 绝对路径，"
            "写出统计 CSV 与 PNG 至 generated/。"
        )
    if mode == "sqlite_join":
        return (
            "直接输出 <Analyze> 和 <Code>，使用 sqlite3.connect(DB_PATH, timeout=30) 执行多表 JOIN，"
            "并将合并结果写入配置指定的 CSV/PNG。"
        )
    if mode == "filesystem_summary":
        return (
            "直接输出 <Analyze> 和 <Code>，仅遍历 generated/ 目录并生成 Markdown 索引，不得执行 SQL。\n\n"
            + build_filesystem_summary_template()
        )
    if mode == "html_report":
        html_name = "multi_table_analysis.html"
        html_files = round_expected_filenames_by_type(rule, "html")
        if html_files:
            html_name = html_files[0]
        return (
            "直接输出 <Analyze> 和 <Code>，遍历 generated/ 目录并使用 pathlib 写入 HTML 报告，禁止直接粘贴 HTML。\n\n"
            + build_html_report_template(html_name)
        )
    return "直接输出 <Analyze> 和 <Code> 完成本轮任务。"


def round_expected_filenames(rule: dict[str, Any]) -> list[str]:
    outputs = rule.get("outputs") or []
    return [out.get("filename") for out in outputs if out.get("filename")]


def round_expected_filenames_by_type(rule: dict[str, Any], type_name: str) -> list[str]:
    type_name = type_name.lower()
    return [
        out.get("filename")
        for out in (rule.get("outputs") or [])
        if (out.get("type") or "").lower() == type_name and out.get("filename")
    ]


def round_expected_types(rule: dict[str, Any]) -> set[str]:
    return {
        (out.get("type") or "").lower()
        for out in (rule.get("outputs") or [])
        if out.get("type")
    }


def round_requires_output_type(rule: dict[str, Any], type_name: str) -> bool:
    type_name = type_name.lower()
    return type_name in round_expected_types(rule)


def round_mode(rule: Optional[dict[str, Any]]) -> str:
    if not rule:
        return ""
    return (rule.get("mode") or "").lower()


def round_input_filename(rule: dict[str, Any]) -> Optional[str]:
    input_cfg = rule.get("input") or {}
    if (input_cfg.get("type") or "").lower() == "csv":
        return input_cfg.get("filename")
    return None


def rule_requires_busy_timeout(rule: dict[str, Any]) -> bool:
    requirements = rule.get("requirements") or []
    return any("pragma busy_timeout" in req.lower() for req in requirements)


def log_prompt_payload(tag: str, prompt_text: str) -> None:
    """将注入给模型的提示词记录到日志，便于排查 prompt 版本。"""
    if not prompt_text:
        return
    max_len = 8000  # 避免日志体积过大
    display_text = (
        prompt_text
        if len(prompt_text) <= max_len
        else prompt_text[:max_len] + "\n...[truncated]..."
    )
    logger.info("[prompt] %s\n%s", tag, display_text)


def build_round_retry_prompt(round_no: int, retry_idx: int) -> str:
    rule = get_round_rule(round_no)
    base = f"⚠️ 检测到第 {round_no} 轮输出为空（已重试 {retry_idx}/3 次）。\n\n"
    if rule and round_mode(rule) == "final_answer":
        prompt = (
            base
            + f"**第 {round_no} 轮任务**：仅输出 `<Answer>` 总结所有轮次的发现与建议。\n\n"
            "**⚡ 立即输出以下格式（不要输出任何其他内容）**：\n\n"
            "<Answer>\n"
            "1. 数据概况……\n"
            "2. 关键发现……\n"
            "3. 后续建议……\n"
            "</Answer>\n"
        )
        prompt += (
            "\n\n**❌ 禁止行为**：\n"
            "- 禁止返回空响应\n"
            "- 禁止等待下一条指令\n"
            "- 禁止输出 <Analyze>/<Code>\n\n"
            "**✅ 必须行为**：立即输出上述 <Answer> 模板"
        )
        return prompt
    if rule:
        desc = describe_round(rule)
        guidance = guidance_for_rule(rule)
        prompt = (
            base + f"**第 {round_no} 轮任务**：{desc}\n\n"
            f"{guidance}\n\n"
            "**⚡ 请立即输出：**\n\n"
            "<Analyze>\n- 说明本轮目标、引用上一轮 <Execute> / 文件\n</Analyze>\n\n"
            "<Code>\n# 根据上述目标编写完整脚本\n</Code>\n"
        )
    else:
        prompt = (
            base + "请参考提示词继续完成剩余分析或输出最终 <Answer>，禁止返回空响应。"
        )

    prompt += (
        "\n\n**❌ 禁止行为**：\n"
        "- 禁止返回空响应\n"
        "- 禁止跳过本轮任务\n"
        "- 禁止输出无关解释或等待指令\n"
        "- 禁止提前输出 <Answer>\n\n"
        "**✅ 必须行为**：立即按照上方格式输出完整内容"
    )
    log_prompt_payload(f"round_{round_no}_retry_{retry_idx}", prompt)
    return prompt


def build_continue_prompt_text(completed_round: int, next_round: int) -> Optional[str]:
    rule = get_round_rule(next_round)
    if not rule:
        return None

    desc = describe_round(rule)
    guidance = guidance_for_rule(rule)
    prompt = (
        f"✅ 已完成第 {completed_round} 轮。\n\n"
        f"⚡ 立即开始第 {next_round} 轮分析（不要等待指令，不要输出任何解释）。\n\n"
        f"**第 {next_round} 轮任务**：{desc}\n\n"
        f"{guidance}"
    )
    log_prompt_payload(f"round_{next_round}_continue", prompt)
    return prompt


def execute_code(code_str):
    import io
    import contextlib
    import traceback

    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(
            stderr_capture
        ):
            exec(code_str, {})
        output = stdout_capture.getvalue()
        if stderr_capture.getvalue():
            output += stderr_capture.getvalue()
        return output
    except Exception as exec_error:
        code_lines = code_str.splitlines()
        tb_lines = traceback.format_exc().splitlines()
        error_line = None
        for line in tb_lines:
            if 'File "<string>", line' in line:
                try:
                    line_num = int(line.split(", line ")[1].split(",")[0])
                    error_line = line_num
                    break
                except (IndexError, ValueError):
                    continue
        error_message = f"Traceback (most recent call last):\n"
        if error_line is not None and 1 <= error_line <= len(code_lines):
            error_message += f'  File "<string>", line {error_line}, in <module>\n'
            error_message += f"    {code_lines[error_line-1].strip()}\n"
        error_message += f"{type(exec_error).__name__}: {str(exec_error)}"
        if stderr_capture.getvalue():
            error_message += f"\n{stderr_capture.getvalue()}"
        return f"[Error]:\n{error_message.strip()}"


def execute_code_safe(
    code_str: str, workspace_dir: str = None, timeout_sec: int = 120
) -> str:
    """在独立进程中执行代码，支持超时，避免阻塞主进程。"""
    if workspace_dir is None:
        workspace_dir = WORKSPACE_BASE_DIR
    exec_cwd = os.path.abspath(workspace_dir)
    os.makedirs(exec_cwd, exist_ok=True)
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=".py", dir=exec_cwd)
        os.close(fd)
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(code_str)
        print(
            f"[exec] Running script: {tmp_path} (timeout={timeout_sec}s) cwd={exec_cwd}"
        )
        # 在子进程中设置无界面环境变量，避免 GUI 后端
        child_env = os.environ.copy()
        child_env.setdefault("MPLBACKEND", "Agg")
        child_env.setdefault("QT_QPA_PLATFORM", "offscreen")
        child_env.pop("DISPLAY", None)

        completed = subprocess.run(
            [sys.executable, tmp_path],
            cwd=exec_cwd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            env=child_env,
        )
        output = (completed.stdout or "") + (completed.stderr or "")
        return output
    except subprocess.TimeoutExpired:
        return f"[Timeout]: execution exceeded {timeout_sec} seconds"
    except Exception as e:
        return f"[Error]: {str(e)}"
    finally:
        try:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


# API endpoint and model path
API_BASE = "http://localhost:8000/v1"  # this localhost is for vllm api, do not change
MODEL_PATH = "qwen3-4b-instruct"  # replace to your path to DeepAnalyze-8B
MAX_ITERATIONS = 20
ANSWER_MIN_EXEC_ROUNDS = 10  # 确保完成第 2-9 轮分析后才请求 Answer
ANSWER_MIN_NON_SCHEMA_ROUNDS = 8  # 对应 8 轮非 schema 代码执行(第 2-9 轮)
MAX_PROMPT_CHARS = getattr(api_config, "MAX_PROMPT_CHARS", 16000)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SQLITE_SEEDS = [
    (
        PROJECT_ROOT
        / "example"
        / "analysis_on_student_loan"
        / "data"
        / "student_loan.sqlite",
        "student_loan.sqlite",
    )
]


# Initialize OpenAI client
client = openai.OpenAI(
    base_url=API_BASE, api_key=getattr(api_config, "OPENAI_API_KEY", "dummy")
)

# Workspace directory
# 确保 workspace 目录相对于 backend.py 所在目录解析
_BACKEND_DIR = Path(__file__).parent.resolve()
WORKSPACE_BASE_DIR = getattr(api_config, "WORKSPACE_BASE_DIR", "workspace")
# 如果是相对路径，则相对于 backend.py 所在目录
if not Path(WORKSPACE_BASE_DIR).is_absolute():
    WORKSPACE_BASE_DIR = str(_BACKEND_DIR / WORKSPACE_BASE_DIR)
HTTP_SERVER_PORT = getattr(api_config, "HTTP_SERVER_PORT", 8100)
HTTP_SERVER_BASE = getattr(
    api_config, "HTTP_SERVER_BASE", f"http://localhost:{HTTP_SERVER_PORT}"
)
WORKSPACE_ROOT = Path(WORKSPACE_BASE_DIR).resolve()
print(f"[启动] WORKSPACE_ROOT = {WORKSPACE_ROOT}")
# you can replace localhost to your local ip


def get_session_workspace(session_id: str) -> str:
    """返回指定 session 的 workspace 路径（workspace/{session_id}/）。"""
    if not session_id:
        session_id = "default"
    session_dir = WORKSPACE_ROOT / session_id
    os.makedirs(session_dir, exist_ok=True)
    return str(session_dir)


def ensure_default_sqlite(workspace_path: Path) -> None:
    """若 workspace 中不存在任何 sqlite 文件，则自动拷贝示例数据，避免模型引用不到真实库。"""
    has_sqlite = any(iter_sqlite_files(workspace_path))
    if has_sqlite:
        return
    for src, dest_name in DEFAULT_SQLITE_SEEDS:
        try:
            if src.exists():
                dest_path = workspace_path / dest_name
                if not dest_path.exists():
                    shutil.copy2(src, dest_path)
                break
        except Exception as copy_error:
            print(f"[ensure_default_sqlite] copy failed: {copy_error}")


def build_download_url(rel_path: str) -> str:
    try:
        encoded = quote(rel_path, safe="/")
    except Exception:
        encoded = rel_path
    return f"{HTTP_SERVER_BASE}/{encoded}"


def workspace_relative_path(path: Path) -> str:
    """返回文件相对于 workspace 根目录的相对路径，用于静态服务器 URL。"""
    try:
        return path.resolve().relative_to(WORKSPACE_ROOT).as_posix()
    except Exception:
        return path.name


# FastAPI app
app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def start_http_server():
    """启动HTTP文件服务器（不修改全局工作目录）。"""
    os.makedirs(WORKSPACE_BASE_DIR, exist_ok=True)
    handler = partial(
        http.server.SimpleHTTPRequestHandler, directory=WORKSPACE_BASE_DIR
    )
    with socketserver.TCPServer(("", HTTP_SERVER_PORT), handler) as httpd:
        print(f"HTTP Server serving {WORKSPACE_BASE_DIR} at port {HTTP_SERVER_PORT}")
        httpd.serve_forever()


# Start HTTP server in a separate thread
threading.Thread(target=start_http_server, daemon=True).start()


# 会话级别的中断标记
SESSION_STOP_FLAGS: Dict[str, bool] = defaultdict(bool)
session_flag_lock = threading.Lock()


def trigger_stop_flag(session_id: str) -> None:
    with session_flag_lock:
        SESSION_STOP_FLAGS[session_id or "default"] = True


def reset_stop_flag(session_id: str) -> None:
    with session_flag_lock:
        SESSION_STOP_FLAGS[session_id or "default"] = False


def should_stop(session_id: str) -> bool:
    with session_flag_lock:
        return SESSION_STOP_FLAGS.get(session_id or "default", False)


def collect_file_info(directory: str) -> str:
    """收集文件信息"""
    all_file_info_str = ""
    dir_path = Path(directory)
    if not dir_path.exists():
        return ""

    files = sorted([f for f in dir_path.iterdir() if f.is_file()])
    for idx, file_path in enumerate(files, start=1):
        size_bytes = os.path.getsize(file_path)
        size_kb = size_bytes / 1024
        size_str = f"{size_kb:.1f}KB"
        file_info = {"name": file_path.name, "size": size_str}
        file_info_str = json.dumps(file_info, indent=4, ensure_ascii=False)
        all_file_info_str += f"File {idx}:\n{file_info_str}\n\n"
    return all_file_info_str


def format_workspace_payload(workspace_payload: list[dict]) -> str:
    """将前端传入的 workspace 文件元信息转换为 prompt 文本。"""
    formatted = []
    for idx, entry in enumerate(workspace_payload, start=1):
        info = {k: v for k, v in entry.items() if v is not None}
        download_url = info.get("download_url")
        info = {
            "name": entry.get("name"),
            "extension": entry.get("extension"),
        }
        size_value = entry.get("size")
        if isinstance(size_value, (int, float)):
            info["size"] = f"{size_value / 1024:.1f}KB"
        elif size_value:
            info["size"] = size_value
        download_url = entry.get("download_url")
        if download_url:
            info["download_url"] = download_url
        formatted.append(
            f"File {idx}:\n" + json.dumps(info, indent=4, ensure_ascii=False) + "\n\n"
        )
    return "".join(formatted).strip()


def iter_sqlite_files(workspace_dir: Path) -> list[Path]:
    """递归枚举 workspace 内的 SQLite 文件列表。"""
    if not isinstance(workspace_dir, Path):
        workspace_dir = Path(workspace_dir)
    found: dict[str, Path] = {}
    for pattern in SQLITE_PATTERNS:
        try:
            for file in workspace_dir.rglob(pattern):
                if file.is_file():
                    found[str(file.resolve())] = file
        except Exception:
            continue
    return sorted(found.values())


def summarize_sqlite_schema(workspace_dir: Path) -> str:
    """遍历 workspace 下的 SQLite 文件并返回表与字段摘要。"""
    summaries: list[str] = []
    for db_file in iter_sqlite_files(workspace_dir):
        try:
            conn = sqlite3.connect(db_file)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            for table in tables:
                cursor.execute(f"PRAGMA table_info('{table}')")
                columns = [col[1] for col in cursor.fetchall()]
                column_desc = ", ".join(columns) if columns else "(无字段)"
                summaries.append(f"{db_file.name}:{table} => {column_desc}")
            conn.close()
        except Exception as exc:
            summaries.append(f"{db_file.name} 读取失败: {exc}")
    return "\n".join(summaries).strip()


def list_sqlite_tables(workspace_dir: Path) -> set[str]:
    """返回 workspace 内所有 sqlite 文件中出现的表名集合。"""
    tables: set[str] = set()
    for db_file in iter_sqlite_files(workspace_dir):
        try:
            conn = sqlite3.connect(db_file)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables.update(row[0] for row in cursor.fetchall() if row and row[0])
            conn.close()
        except Exception:
            continue
    return tables


TABLE_TOKEN_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
SQL_TABLE_PATTERN = re.compile(
    r"(?:from|join|into|update|table)\s+([A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)
SQL_PRAGMA_PATTERN = re.compile(
    r"pragma\s+table_info\s*\(\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)
DDL_TABLE_PATTERN = re.compile(
    r"\b(create|drop|alter)\s+table\b", re.IGNORECASE | re.MULTILINE
)


def extract_table_mentions_from_text(
    text: str, known_tables: set[str]
) -> tuple[set[str], set[str]]:
    """从自然语言描述中提取疑似表名。仅用于提示，不触发强制校验。"""
    tokens = set(TABLE_TOKEN_PATTERN.findall(text or ""))
    normalized_known = {tbl.lower() for tbl in known_tables}

    COMMON_WORDS = COMMON_WORDS_GLOBAL
    FILE_SUFFIXES = {
        "summary",
        "dist",
        "distribution",
        "count",
        "info",
        "data",
        "result",
        "chart",
        "plot",
        "graph",
        "readme",
        "report",
        "analysis",
    }

    # Python 内置函数和常见变量名白名单（用于 Round 8/9 文件系统操作）
    PYTHON_BUILTINS = {
        "build_list",
        "format_items",
        "html_lines",
        "time_stats",
        "analysis_summary",
        "key_findings",
        "readme_path",
        "generated_dir",
        "csv_files",
        "png_files",
        "log_files",
        "html_files",
        "other_files",
        "st_size",
        "stat",
        "exists",
        "iterdir",
        "write_text",
        "read_text",
        "print",
        "bytes",
        "visual",
        "section",
        "now",
        "strptime",
        "strftime",
        "datetime",
        "timedelta",
        "yyyy",
        "mm",
        "dd",
        "hh",
        "ss",
    }

    def is_likely_table(token: str) -> bool:
        lowered = token.lower()
        if not lowered:
            return False
        if lowered in COMMON_WORDS or lowered.startswith("session_"):
            return False
        # 过滤 Python 内置函数和常见变量名
        if lowered in PYTHON_BUILTINS:
            return False
        # 过滤常见的 Python 变量命名后缀（DataFrame、路径等）
        if lowered.endswith(
            (
                "_df",
                "_path",
                "_dir",
                "_file",
                "_files",
                "_data",
                "_summary",
                "_count",
                "_flag",
            )
        ):
            return False
        if "_" in lowered:
            parts = lowered.split("_")
            if len(parts) >= 2 and parts[-1] in FILE_SUFFIXES:
                return False
            if len(parts) >= 2 and parts[-1] in COMMON_WORDS:
                return False
            # 长下划线 token 很可能是文件/字段描述,两段以上直接跳过
            if len(parts) >= 3 and lowered not in normalized_known:
                return False
        if lowered.endswith(("csv", "png", "txt")):
            return False
        # 针对 multi_table_join_result 这类生成文件的命名进行额外过滤
        if lowered.endswith(("join_result", "join_results")):
            return False
        if (
            lowered.startswith(("multi_", "single_"))
            and lowered not in normalized_known
        ):
            return False
        return True

    known: set[str] = set()
    unknown: set[str] = set()
    for tok in tokens:
        tok_lower = tok.lower()
        if tok_lower in normalized_known:
            known.add(next(tbl for tbl in known_tables if tbl.lower() == tok_lower))
            continue
        if not is_likely_table(tok):
            continue
        unknown.add(tok)
    return known, unknown


def extract_sql_table_names(code: str) -> set[str]:
    """从代码中提取 SQL 语句中引用的表名，过滤掉 Python 模块名和常见标识符。"""
    tables = set(SQL_TABLE_PATTERN.findall(code or ""))
    tables.update(SQL_PRAGMA_PATTERN.findall(code or ""))

    # 过滤掉 Python 标准库模块名、常见变量名、以及可能出现在注释/字符串中的词
    PYTHON_KEYWORDS = {
        # Python 模块和库
        "pathlib",
        "sqlite3",
        "pandas",
        "matplotlib",
        "seaborn",
        "numpy",
        "pd",
        "plt",
        "sns",
        "np",
        # 常见变量名
        "conn",
        "cursor",
        "df",
        "summary",
        "Path",
        "OUTPUT_DIR",
        "DB_PATH",
        "data",
        "result",
        "query",
        "stats",
        "merged",
        "merged_df",
        "school_counts",
        "school_top3",
        "bankrupt_absence",
        "non_bankrupt_absence",
        "absence_stats",
        "bankrupcy_df",
        "absence_df",
        "enrolled_df",
        "filed_for_bankrupcy_df",
        "longest_absense_df",
        # Pandas/Matplotlib 方法和参数
        "include",
        "all",
        "transpose",
        "reset_index",
        "index",
        "False",
        "True",
        "None",
        "encoding",
        "utf",
        "parents",
        "exist_ok",
        "timeout",
        "dpi",
        "figsize",
        "tight_layout",
        "countplot",
        "barplot",
        "head",
        "tail",
        "describe",
        "value_counts",
        "fillna",
        "astype",
        "merge",
        "crosstab",
        "margins",
        # 常见的分析相关词汇（可能出现在注释或字符串中）
        "analysis",
        "completed",
        "distribution",
        "joint",
        "bankrupt",
        "non",
        "vs",
        "top",
        "top3",
        "absence",
        "duration",
        "error",
        "connecting",
        "database",
        "validating",
        "validation",
        "available",
        "columns",
        "required",
        "tables",
        "exist",
        "correctly",
        "named",
        "proceeding",
        "reading",
        "executing",
        "generating",
        "saving",
        "printing",
        # SQLite 元数据字段名（sqlite_master 的列名，不是表名）
        "table_name",
        "sql",
        "schema",
        "rows",
        "SQL",
        "type",
        "name",
        "tbl_name",
        "rootpage",
        "sqlite_master",
        "sqlite_sequence",
    }

    COMMON_WORDS = COMMON_WORDS_GLOBAL
    return {
        tbl
        for tbl in tables
        if tbl.lower() not in PYTHON_KEYWORDS and tbl.lower() not in COMMON_WORDS
    }


def snapshot_workspace_files(directory: str) -> set[str]:
    """生成 workspace 目录下所有文件的绝对路径集合。"""
    try:
        return {str(p.resolve()) for p in Path(directory).rglob("*") if p.is_file()}
    except Exception:
        return set()


def get_file_icon(extension):
    """获取文件图标"""
    ext = extension.lower()
    icons = {
        (".jpg", ".jpeg", ".png", ".gif", ".bmp"): "🖼️",
        (".pdf",): "📕",
        (".doc", ".docx"): "📘",
        (".txt",): "📄",
        (".md",): "📝",
        (".csv", ".xlsx"): "📊",
        (".json", ".sqlite"): "🗄️",
        (".mp4", ".avi", ".mov"): "🎥",
        (".mp3", ".wav"): "🎵",
        (".zip", ".rar", ".tar"): "🗜️",
    }

    for extensions, icon in icons.items():
        if ext in extensions:
            return icon
    return "📁"


def uniquify_path(target: Path) -> Path:
    """若目标已存在，生成 'name (1).ext'、'name (2).ext' 形式的新路径。"""
    if not target.exists():
        return target
    parent = target.parent
    stem = target.stem
    suffix = target.suffix
    import re as _re

    m = _re.match(r"^(.*) \((\d+)\)$", stem)
    base = stem
    start = 1
    if m:
        base = m.group(1)
        try:
            start = int(m.group(2)) + 1
        except Exception:
            start = 1
    i = start
    while True:
        candidate = parent / f"{base} ({i}){suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def execute_code(code_str):
    """执行Python代码"""
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(
            stderr_capture
        ):
            exec(code_str, {})
        output = stdout_capture.getvalue()
        if stderr_capture.getvalue():
            output += stderr_capture.getvalue()
        return output
    except Exception as exec_error:
        return f"[Error]: {str(exec_error)}"


# API Routes
@app.get("/workspace/files")
async def get_workspace_files(session_id: str = Query("default")):
    """获取工作区文件列表（支持 session 隔离）"""
    workspace_dir = get_session_workspace(session_id)
    generated_dir = Path(workspace_dir) / "generated"
    # 获取 generated 目录下的文件名集合
    generated_files = (
        set(f.name for f in generated_dir.iterdir() if f.is_file())
        if generated_dir.exists()
        else set()
    )

    files = []
    for file_path in Path(workspace_dir).iterdir():
        if file_path.is_file():
            if file_path.name in generated_files:
                continue
            stat = file_path.stat()
            rel_path = f"{session_id}/{file_path.name}"
            files.append(
                {
                    "name": file_path.name,
                    "size": stat.st_size,
                    "extension": file_path.suffix.lower(),
                    "icon": get_file_icon(file_path.suffix),
                    "download_url": build_download_url(rel_path),
                    "preview_url": (
                        build_download_url(rel_path)
                        if file_path.suffix.lower()
                        in [
                            ".jpg",
                            ".jpeg",
                            ".png",
                            ".gif",
                            ".bmp",
                            ".pdf",
                            ".txt",
                            ".doc",
                            ".docx",
                            ".csv",
                            ".xlsx",
                        ]
                        else None
                    ),
                }
            )
    return {"files": files}


# ---------- Workspace Tree & Single File Delete ----------
def _rel_path(path: Path, root: Path) -> str:
    try:
        rel = path.relative_to(root)
        return rel.as_posix()
    except Exception:
        return path.name


def build_tree(path: Path, root: Path | None = None) -> dict:
    if root is None:
        root = path
    node: dict = {
        "name": path.name or "workspace",
        "path": _rel_path(path, root),
        "is_dir": path.is_dir(),
    }
    if path.is_dir():
        children = []

        # 自定义排序：generated 文件夹放在最后，其他按目录优先、名称排序
        def sort_key(p):
            is_generated = p.name == "generated"
            is_dir = p.is_dir()
            return (is_generated, not is_dir, p.name.lower())

        for child in sorted(path.iterdir(), key=sort_key):
            if child.name.startswith("."):
                continue
            children.append(build_tree(child, root))
        node["children"] = children
    else:
        node["size"] = path.stat().st_size
        node["extension"] = path.suffix.lower()
        node["icon"] = get_file_icon(path.suffix)
        rel = _rel_path(path, root)
        node["download_url"] = build_download_url(rel)
    return node


@app.get("/workspace/tree")
async def workspace_tree(session_id: str = Query("default")):
    workspace_dir = get_session_workspace(session_id)
    root = Path(workspace_dir)
    tree_data = build_tree(root, root)

    # 在下载链接前加上 session_id 前缀
    def prefix_urls(node, sid):
        if "download_url" in node and node["download_url"]:
            # 重新构建包含 session_id 的路径
            rel = node.get("path", "")
            node["download_url"] = build_download_url(f"{sid}/{rel}")
        if "children" in node:
            for child in node["children"]:
                prefix_urls(child, sid)

    prefix_urls(tree_data, session_id)
    return tree_data


@app.delete("/workspace/file")
async def delete_workspace_file(
    path: str = Query(..., description="relative path under workspace"),
    session_id: str = Query("default"),
):
    workspace_dir = get_session_workspace(session_id)
    abs_workspace = Path(workspace_dir).resolve()
    target = (abs_workspace / path).resolve()
    if abs_workspace not in target.parents and target != abs_workspace:
        raise HTTPException(status_code=400, detail="Invalid path")
    if not target.exists():
        raise HTTPException(status_code=404, detail="Not found")
    if target.is_dir():
        raise HTTPException(status_code=400, detail="Folder deletion not allowed")
    try:
        target.unlink()
        return {"message": "deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/workspace/move")
async def move_path(
    src: str = Query(..., description="relative source path under workspace"),
    dst_dir: str = Query("", description="relative target directory under workspace"),
    session_id: str = Query("default"),
):
    """在同一 workspace 内移动（或重命名）文件/目录。
    - src: 源相对路径（必填）
    - dst_dir: 目标目录（相对路径，空表示移动到根目录）
    """
    workspace_dir = get_session_workspace(session_id)
    abs_workspace = Path(workspace_dir).resolve()

    abs_src = (abs_workspace / src).resolve()
    if abs_workspace not in abs_src.parents and abs_src != abs_workspace:
        raise HTTPException(status_code=400, detail="Invalid src path")
    if not abs_src.exists():
        raise HTTPException(status_code=404, detail="Source not found")

    abs_dst_dir = (abs_workspace / (dst_dir or "")).resolve()
    if abs_workspace not in abs_dst_dir.parents and abs_dst_dir != abs_workspace:
        raise HTTPException(status_code=400, detail="Invalid dst_dir path")
    abs_dst_dir.mkdir(parents=True, exist_ok=True)

    target = abs_dst_dir / abs_src.name
    target = uniquify_path(target)
    try:
        shutil.move(str(abs_src), str(target))
        rel_new = str(target.relative_to(abs_workspace))
        return {"message": "moved", "new_path": rel_new}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Move failed: {e}")


@app.delete("/workspace/dir")
async def delete_workspace_dir(
    path: str = Query(..., description="relative directory under workspace"),
    recursive: bool = Query(True, description="delete directory recursively"),
    session_id: str = Query("default"),
):
    """删除 workspace 下的目录。默认递归删除，禁止删除根目录。"""
    workspace_dir = get_session_workspace(session_id)
    abs_workspace = Path(workspace_dir).resolve()
    target = (abs_workspace / path).resolve()
    if abs_workspace not in target.parents and target != abs_workspace:
        raise HTTPException(status_code=400, detail="Invalid path")
    if target == abs_workspace:
        raise HTTPException(status_code=400, detail="Cannot delete workspace root")
    if not target.exists():
        raise HTTPException(status_code=404, detail="Not found")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="Not a directory")
    try:
        if recursive:
            shutil.rmtree(target)
        else:
            target.rmdir()
        return {"message": "deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/proxy")
async def proxy(url: str):
    """Simple CORS proxy for previewing external files.
    WARNING: For production, add domain allowlist and authentication.
    """
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            r = await client.get(url)
        return Response(
            content=r.content,
            media_type=r.headers.get("content-type", "application/octet-stream"),
            headers={"Access-Control-Allow-Origin": "*"},
            status_code=r.status_code,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Proxy fetch failed: {e}")


@app.post("/workspace/upload")
async def upload_files(
    files: List[UploadFile] = File(...), session_id: str = Query("default")
):
    """上传文件到工作区（支持 session 隔离）"""
    workspace_dir = get_session_workspace(session_id)
    uploaded_files = []

    for file in files:
        # 唯一化文件名，避免覆盖
        dst = uniquify_path(Path(workspace_dir) / file.filename)
        with open(dst, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
        uploaded_files.append(
            {
                "name": dst.name,
                "size": len(content),
                "path": str(dst.relative_to(Path(workspace_dir))),
            }
        )

    return {
        "message": f"Successfully uploaded {len(uploaded_files)} files",
        "files": uploaded_files,
    }


@app.delete("/workspace/clear")
async def clear_workspace(session_id: str = Query("default")):
    """清空工作区（支持 session 隔离）"""
    workspace_dir = get_session_workspace(session_id)
    if os.path.exists(workspace_dir):
        shutil.rmtree(workspace_dir)
    os.makedirs(workspace_dir, exist_ok=True)
    return {"message": "Workspace cleared successfully"}


@app.post("/workspace/upload-to")
async def upload_to_dir(
    dir: str = Query("", description="relative directory under workspace"),
    files: List[UploadFile] = File(...),
    session_id: str = Query("default"),
):
    """上传文件到 workspace 下的指定子目录（仅限工作区内）。"""
    workspace_dir = get_session_workspace(session_id)
    abs_workspace = Path(workspace_dir).resolve()
    target_dir = (abs_workspace / dir).resolve()
    if abs_workspace not in target_dir.parents and target_dir != abs_workspace:
        raise HTTPException(status_code=400, detail="Invalid dir path")
    target_dir.mkdir(parents=True, exist_ok=True)

    saved = []
    for f in files:
        dst = uniquify_path(target_dir / f.filename)
        try:
            with open(dst, "wb") as buffer:
                content = await f.read()
                buffer.write(content)
            saved.append(
                {
                    "name": dst.name,
                    "size": len(content),
                    "path": str(dst.relative_to(abs_workspace)),
                }
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Save failed: {e}")
    return {"message": f"uploaded {len(saved)}", "files": saved}


@app.post("/execute")
async def execute_code_api(request: dict):
    """执行 Python 代码"""
    print("🔥 Execute API called:", request)  # Debug log

    try:
        code = request.get("code", "")
        session_id = request.get("session_id", "default")
        workspace_dir = get_session_workspace(session_id)

        if not code:
            raise HTTPException(status_code=400, detail="No code provided")

        print(f"Executing code: {code[:100]}...")  # Debug log (first 100 chars)

        # 使用子进程安全执行，避免 GUI/线程问题（在指定 session workspace 中）
        result = execute_code_safe(code, workspace_dir)
        print(f"✅ Execution result: {result[:200]}...")  # Debug log

        return {
            "success": True,
            "result": result,
            "message": "Code executed successfully",
        }

    except Exception as e:
        print(f"❌ Execution error: {traceback.format_exc()}")  # Debug log
        return {
            "success": False,
            "result": f"Error: {str(e)}",
            "message": "Code execution failed",
        }


def fix_code_block(content):
    def fix_text(text):
        stack = []
        lines = text.splitlines(keepends=True)
        result = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("```python"):
                if stack and stack[-1] == "```python":
                    result.append("```\n")
                    stack.pop()
                stack.append("```python")
                result.append(line)
            elif stripped == "```":
                if stack and stack[-1] == "```python":
                    stack.pop()
                result.append(line)
            else:
                result.append(line)
        while stack:
            result.append("```\n")
            stack.pop()
        return "".join(result)

    if isinstance(content, str):
        return fix_text(content)
    elif isinstance(content, tuple):
        text_part = content[0] if content[0] else ""
        return (fix_text(text_part), content[1])
    return content


def fix_tags_and_codeblock(s: str) -> str:
    """
    修复未闭合的tags，并确保</Code>后代码块闭合。
    """
    pattern = re.compile(
        r"<(Analyze|Understand|Code|Execute|Answer)>(.*?)(?:</\1>|(?=$))", re.DOTALL
    )

    # 找所有匹配
    matches = list(pattern.finditer(s))
    if not matches:
        return s  # 没有标签，直接返回

    # 检查最后一个匹配是否闭合
    last_match = matches[-1]
    tag_name = last_match.group(1)
    matched_text = last_match.group(0)

    if not matched_text.endswith(f"</{tag_name}>"):
        # 没有闭合，补上
        if tag_name == "Code":
            s = fix_code_block(s) + f"\n```\n</{tag_name}>"
        else:
            s += f"\n</{tag_name}>"

    return s


EMOJI_TAG_MAP = {
    "🔍Analyze": "<Analyze>",
    "💻Code": "<Code>",
    "⚡Execute": "<Execute>",
    "📎File": "<File>",
    "✅Answer": "<Answer>",
}

HEADING_TAG_PATTERN = re.compile(
    r"^\s{0,3}#{2,3}\s*(Analyze|Code|Execute|File|Answer)\s*$",
    re.MULTILINE,
)
FILE_TAG_CAPTURE_PATTERN = re.compile(r"<File>(.*?)</File>", re.DOTALL)
FILES_OPEN_PATTERN = re.compile(r"<\s*Files\s*>", re.IGNORECASE)
FILES_CLOSE_PATTERN = re.compile(r"<\s*/\s*Files\s*>", re.IGNORECASE)
MODEL_FILE_TAG_PATTERN = re.compile(r"<File>.*?</File>", re.DOTALL)
# 匹配连续出现的 assistant（包括后面跟任意字符的情况）
ASSISTANT_ECHO_PATTERN = re.compile(r"(?:\bassistant\b[\s\n]*){2,}", re.IGNORECASE)
# 匹配 assistant 开头的重复文本段落（如 "assistant 根据第 2 轮 <Execute </Analyze>"）
ASSISTANT_PARAGRAPH_PATTERN = re.compile(
    r"(\bassistant\b[^\n<]{10,100}?)(\1){1,}", re.IGNORECASE
)
SEPARATOR_PATTERN = re.compile(r"(?:^|\n)([-=_*]{2,}\s*\n){3,}", re.MULTILINE)
FILE_NAME_PATTERN = re.compile(
    r"([\w\-.]+\.(?:csv|tsv|txt|md|json|png|jpg|jpeg|gif|svg|pdf|xlsx|xls|parquet))",
    re.IGNORECASE,
)
FILENAME_SUFFIX_CLEANER = re.compile(r"\s+\(\d+\)$")
SQLITE_CONNECT_PATTERN = re.compile(
    r"sqlite3\.connect\(\s*(?:r)?['\"]([^'\"]+)['\"]\s*\)", re.IGNORECASE
)
PROHIBITED_TABLES = {"information_schema", "pg_catalog", "mysql", "sys"}
MARKDOWN_PREFIXES = (
    "# ",
    "##",
    "###",
    "####",
    "#####",
    "######",
    "* ",
    "- ",
    "> ",
    "|",
    "```",
    "<!--",
)


def code_looks_like_markdown(code: str) -> bool:
    """Heuristic check: detect when the model直接粘贴 Markdown 内容而非 Python 代码。"""
    if not code:
        return False

    normalized = code.strip()
    if not normalized:
        return False

    # 若包含典型 Python 语法，则认为不是 Markdown
    python_tokens = (
        "import ",
        "from ",
        "with ",
        "open(",
        ".write(",
        ".write_text(",
        ".writelines(",
        "Path(",
        "os.",
        "json.",
    )
    lower_code = normalized.lower()
    if any(token in lower_code for token in python_tokens):
        return False

    significant_lines = [
        line.lstrip() for line in normalized.splitlines() if line.strip()
    ]
    if not significant_lines:
        return False

    markdown_like = sum(
        1 for line in significant_lines[:5] if line.startswith(MARKDOWN_PREFIXES)
    )
    return any(token in lower_code for token in python_tokens)


def code_looks_like_html(code: str) -> bool:
    """Detect cases where模型直接粘贴 HTML，而未提供 Python 代码。"""
    if not code:
        return False
    normalized = code.strip()
    if not normalized:
        return False
    python_tokens = (
        "import ",
        "from ",
        "with ",
        "open(",
        ".write(",
        ".write_text(",
        ".writelines(",
        "Path(",
        "os.",
    )
    lower_code = normalized.lower()
    if any(token in lower_code for token in python_tokens):
        return False
    # 如果包含典型 HTML 根元素且缺少 Python 结构，则判定为 HTML
    return "<html" in lower_code and "</html>" in lower_code


def has_filesystem_write_operations(code: str) -> bool:
    """Round 8 代码必须包含真实写盘操作（write_text / write / writelines）。"""
    if not code:
        return False
    lower_code = code.lower()
    write_tokens = (
        ".write_text(",
        ".write(",
        ".writelines(",
    )
    has_write_call = any(token in lower_code for token in write_tokens)
    if not has_write_call:
        return False
    path_tokens = (
        "path(",
        "from pathlib import",
        "open(",
    )
    return any(token in lower_code for token in path_tokens)


HTML_SECTION_IDS = ("summary", "visual", "data", "readme")


def html_report_has_required_structure(text: str) -> tuple[bool, list[str]]:
    """检测 multi_table_analysis.html 是否包含基础结构与必备 section。"""
    if not text:
        return False, ["HTML 内容为空"]
    lower = text.lower()
    missing: list[str] = []
    if "<html" not in lower:
        missing.append("缺少 <html> 标签")
    if "<head" not in lower:
        missing.append("缺少 <head> 段")
    if "<body" not in lower:
        missing.append("缺少 <body> 段")
    for section_id in HTML_SECTION_IDS:
        if f'id="{section_id}"' not in lower and f"id='{section_id}'" not in lower:
            missing.append(f"缺少 id='{section_id}' 段落")
    if "readme" not in lower:
        missing.append("正文未提及 README")
    return (not missing), missing


HTML_PLACEHOLDER_PATTERN = re.compile(r"\{\s*(rows|cols)\s*\}", re.IGNORECASE)


def html_report_has_placeholders(text: str) -> bool:
    if not text:
        return False
    return bool(HTML_PLACEHOLDER_PATTERN.search(text))


def html_report_has_unfriendly_numpy_repr(text: str) -> bool:
    if not text:
        return False
    lower = text.lower()
    return "np.int" in lower or "np.float" in lower or "numpy." in lower


def html_report_references_any_columns(text: str, columns: list[str]) -> bool:
    if not text or not columns:
        return False
    # 仅做简单子串匹配：列名来源于真实 df.columns，不 hardcode 业务字段。
    for col in columns:
        if col and str(col) in text:
            return True
    return False


def normalize_filename(name: str) -> str:
    """统一文件名对比：去除 (n)/_modified 等后缀并转小写。"""
    if not name:
        return ""
    name = name.strip()
    try:
        path = Path(name)
        stem = FILENAME_SUFFIX_CLEANER.sub("", path.stem)
        stem = stem.removesuffix("_modified")
        return f"{stem}{path.suffix}".lower()
    except Exception:
        return name.lower()


def extract_file_claims(content: str) -> set[str]:
    """解析模型在 <File> 中声明的文件名集合。"""
    claims: set[str] = set()
    if not content:
        return claims
    for block in FILE_TAG_CAPTURE_PATTERN.findall(content):
        for match in FILE_NAME_PATTERN.findall(block):
            normalized = normalize_filename(match)
            if normalized:
                claims.add(normalized)
    return claims


def strip_model_file_blocks(content: str) -> str:
    """移除模型原始响应中的 <File> 段（包含未闭合的尾部），避免未校验链接直接展示给前端。"""
    if not content:
        return content
    cleaned = MODEL_FILE_TAG_PATTERN.sub("", content)
    last_open = cleaned.find("<File>")
    while last_open != -1:
        last_close = cleaned.find("</File>", last_open)
        if last_close == -1:
            cleaned = cleaned[:last_open]
            break
        cleaned = cleaned[:last_open] + cleaned[last_close + len("</File>") :]
        last_open = cleaned.find("<File>")

    # 防御：部分模型会在 </Code> 之后继续输出“schema / Code / sql”块（常见为重复提示或虚构表结构）。
    # 这类内容不属于对话协议，且会污染消息历史并导致后续轮次输出膨胀。
    schema_tail = re.search(
        r"\n\s*schema\s*\n\s*Code\s*\n\s*sql\s*\n",
        cleaned,
        re.IGNORECASE,
    )
    if schema_tail:
        cleaned = cleaned[: schema_tail.start()].rstrip()
    return cleaned


HTML_WRAPPER_TAGS = ("div", "section", "article", "main", "blockquote", "response")
HTML_WRAPPER_PATTERN = re.compile(
    r"^\s*<(?P<tag>"
    + "|".join(HTML_WRAPPER_TAGS)
    + r")\b[^>]*>(?P<body>.*)</(?P=tag)>\s*$",
    re.IGNORECASE | re.DOTALL,
)


def strip_outer_html_wrappers(content: str) -> str:
    """剥离模型响应外层纯展示用的 HTML 容器，保留核心 <Analyze>/<Code> 内容。"""
    if not content:
        return content
    trimmed = content.strip()
    # 最多剥 5 层，避免无限循环
    for _ in range(5):
        match = HTML_WRAPPER_PATTERN.match(trimmed)
        if not match:
            break
        trimmed = match.group("body").strip()
    return trimmed


def normalize_model_tags(content: str) -> str:
    """将常见的 emoji 标签转换为标准 <Tag> 形式，并移除重复的分隔线和 assistant 回显。"""
    if not content:
        return content
    normalized = strip_outer_html_wrappers(content)
    # 兼容某些前端/模型会把 emoji 与标题拆成多行的情况，例如：
    # "💻\nCode"、"🔍\nAnalyze"、"⚡\nExecute"
    normalized = re.sub(r"🔍\s*\n\s*Analyze\b", "<Analyze>", normalized)
    normalized = re.sub(r"💻\s*\n\s*Code\b", "<Code>", normalized)
    normalized = re.sub(r"⚡\s*\n\s*Execute\b", "<Execute>", normalized)
    normalized = re.sub(r"📎\s*\n\s*File\b", "<File>", normalized)
    normalized = re.sub(r"✅\s*\n\s*Answer\b", "<Answer>", normalized)
    for emoji_tag, canonical in EMOJI_TAG_MAP.items():
        normalized = normalized.replace(emoji_tag, canonical)
    normalized = HEADING_TAG_PATTERN.sub(lambda m: f"<{m.group(1)}>", normalized)
    # 兼容 "Code\npython" / "Code\npython\n..." 这种非 fenced / 非 <Code> 的代码开头。
    # 只在尚未出现 <Code> 时进行替换，避免误伤正文中的普通单词。
    if "<Code>" not in normalized:
        normalized = re.sub(
            r"(^|\n)\s*Code\s*\n\s*python\s*(?=\n)",
            r"\1<Code>\n```python\n",
            normalized,
            flags=re.IGNORECASE,
        )
        normalized = re.sub(
            r"(^|\n)\s*Code\s*(?=\n\s*```)",
            r"\1<Code>\n",
            normalized,
            flags=re.IGNORECASE,
        )
    normalized = FILES_OPEN_PATTERN.sub("<File>", normalized)
    normalized = FILES_CLOSE_PATTERN.sub("</File>", normalized)
    # 先移除 assistant 开头的重复段落（如 "assistant 根据第 2 轮 <Execute </Analyze>"）
    normalized = ASSISTANT_PARAGRAPH_PATTERN.sub(r"\1", normalized)
    # 再移除连续的 assistant 词
    normalized = ASSISTANT_ECHO_PATTERN.sub("", normalized)
    # 移除连续 3 次以上的分隔线，保留最多 2 次
    normalized = SEPARATOR_PATTERN.sub(lambda m: m.group(1) * 2, normalized)
    # 修复错误的代码块格式：Codepython -> ```python
    normalized = re.sub(r"\bCodepython\b", "```python", normalized)
    # 移除噪音词（如 assistant、unicorn、acer 等重复出现的无意义词）
    normalized = re.sub(r"\b(unicorn|acer)\b\s*", "", normalized, flags=re.IGNORECASE)
    return normalized


SQLITE_PATTERNS = ("*.sqlite", "*.db", "*.db3")


def find_primary_sqlite(workspace_path: Path) -> Path | None:
    """在 workspace 中（递归）定位首个 sqlite 文件。"""
    for pattern in SQLITE_PATTERNS:
        try:
            candidates = sorted(workspace_path.rglob(pattern))
        except Exception as api_error:
            error_block = (
                "\n<Answer>\n"
                "调用底层模型接口超时或失败，无法继续生成下一轮响应。"
                f" 具体错误：{api_error}。请确认 vLLM/DeepAnalyze 模型服务（{MODEL_PATH} @ {API_BASE}）已正常启动，"
            )
            return error_block
        for file in candidates:
            if file.is_file():
                return file
    return None


def build_schema_bootstrap_block(workspace_path: Path) -> str:
    """生成首轮自动列出 CSV 文件路径和 SQLite 表结构的模板响应。"""
    db_path = find_primary_sqlite(workspace_path)
    if not db_path:
        return ""
    # 使用绝对路径，确保代码执行时能找到数据库文件
    db_name = str(db_path.resolve())
    print(
        f"[build_schema_bootstrap_block] workspace_path={workspace_path}, db_name={db_name}"
    )

    # 查找 data 目录下的所有 CSV 文件
    data_dir = workspace_path / "data"
    csv_files = []
    if data_dir.exists():
        csv_files = sorted([f for f in data_dir.glob("*.csv")])

    analyze = (
        "<Analyze>\n"
        "系统检测到模型尚未正确进入首轮分析，已自动补充：当前目标=列出所有 CSV 数据文件路径和 SQLite 表结构，"
        "供后续分析引用。\n"
        "</Analyze>\n"
    )
    query_lines = "\n".join(
        [
            "SELECT name AS table_name, type, sql",
            "FROM sqlite_master",
            "WHERE type IN ('table', 'view');",
        ]
    )

    # 构建代码块
    code_parts = [
        "<Code>\n",
        "```python\n",
        "import sqlite3\n",
        "import pandas as pd\n",
        "from pathlib import Path\n",
        "\n",
        "# ========== 第一部分：CSV 数据文件路径 ==========\n",
        "print('='*80)\n",
        "print('【CSV 数据文件路径】')\n",
        "print('='*80)\n",
    ]

    # 添加 CSV 文件路径
    if csv_files:
        for csv_file in csv_files:
            csv_abs_path = str(csv_file.resolve())
            file_name = csv_file.name
            code_parts.append(f'print(f"{file_name}: {csv_abs_path!r}")\n')
    else:
        code_parts.append('print("未找到 CSV 文件")\n')

    # 添加 SQLite 表结构查询和CSV导出
    code_parts.extend(
        [
            "\n",
            "# ========== 第二部分：SQLite 数据库表结构 ==========\n",
            f'conn = sqlite3.connect(r"{db_name}")\n',
            f'query = """\n{query_lines}\n"""\n',
            "schema_df = pd.read_sql_query(query, conn)\n",
            "print('\\n' + '='*80)\n",
            "print('【SQLite 数据库表结构】')\n",
            "print('='*80)\n",
            "print(schema_df)\n",
            "print('\\n' + '='*80)\n",
            "print('【表字段详情】')\n",
            "print('='*80)\n",
            "for table_name in schema_df['table_name']:\n",
            "    cursor = conn.cursor()\n",
            "    cursor.execute(f'PRAGMA table_info({table_name})')\n",
            "    columns = cursor.fetchall()\n",
            "    print(f'\\n表名: {table_name}')\n",
            "    print(f'字段: {\", \".join([col[1] for col in columns])}')\n",
            "\n",
            "# ========== 第三部分：导出表为CSV文件 ==========\n",
            f"data_dir = Path(r'{str(workspace_path)}') / 'data'\n",
            "data_dir.mkdir(parents=True, exist_ok=True)\n",
            "print('\\n' + '='*80)\n",
            "print('【导出CSV文件】')\n",
            "print('='*80)\n",
            "for table_name in schema_df['table_name']:\n",
            "    df = pd.read_sql_query(f'SELECT * FROM {table_name}', conn)\n",
            "    csv_path = data_dir / f'{table_name}.csv'\n",
            "    df.to_csv(csv_path, index=False, encoding='utf-8')\n",
            "    print(f'已导出: {table_name}.csv ({len(df)} 行)')\n",
            "conn.close()\n",
            "```\n",
            "</Code>",
        ]
    )

    code = "".join(code_parts)
    return analyze + "\n" + code


def run_schema_bootstrap(workspace_path: Path, session_id: str = None) -> str:
    """执行首轮 schema 查询并返回完整 <Analyze>/<Code>/<Execute> 块。"""
    block = build_schema_bootstrap_block(workspace_path)
    if not block:
        return ""

    # 获取数据库绝对路径
    db_path = find_primary_sqlite(workspace_path)
    db_name = str(db_path.resolve()) if db_path else ""

    code_match = re.search(r"```python(.*?)```", block, re.DOTALL)
    script = code_match.group(1).strip() if code_match else ""
    if not script:
        return block
    output = execute_code_safe(script, str(workspace_path))

    # 写入执行日志到 generated 目录
    if session_id:
        generated_dir = workspace_path / "generated"
        generated_dir.mkdir(parents=True, exist_ok=True)
        try:
            log_file = generated_dir / "execute_round_0_bootstrap.txt"
            with open(log_file, "w", encoding="utf-8") as f:
                from datetime import datetime

                f.write("=== Schema Bootstrap Execution ===\n")
                f.write(f"Session: {session_id}\n")
                f.write(f"Timestamp: {datetime.now():%Y-%m-%d %H:%M:%S}\n")
                f.write(f"Workspace: {workspace_path}\n\n")
                f.write("=== Code ===\n")
                f.write(script)
                f.write("\n\n=== Output ===\n")
                f.write(output)
            print(f"[run_schema_bootstrap] Wrote bootstrap log to {log_file}")
        except Exception as log_err:
            print(f"[Warning] Failed to write bootstrap log: {log_err}")

    exe_block = f"\n<Execute>\n```\n{output}\n```\n</Execute>\n"

    # 查找 CSV 文件路径
    data_dir = workspace_path / "data"
    csv_files = []
    if data_dir.exists():
        csv_files = sorted([f for f in data_dir.glob("*.csv")])

    # 构建 CSV 文件路径列表
    csv_paths_text = ""
    if csv_files:
        csv_paths_text = "\n".join(
            [f"- {f.name}: `{str(f.resolve())}`" for f in csv_files]
        )

    # 明确告知模型数据库的绝对路径，并提供完整的代码模板
    db_path_reminder = (
        f"\n{'='*80}\n"
        f"**【数据库绝对路径】请在后续所有代码中使用以下路径**：\n\n"
        f"```python\n"
        f'DB_PATH = r"{db_name}"\n'
        f"```\n"
        f"{'='*80}\n\n"
        f"**【CSV 文件路径】第 2-6 轮必须使用以下 CSV 文件**：\n\n"
        f"{csv_paths_text}\n\n"
        f"{'='*80}\n\n"
        "**【代码模板 A】第 2-6 轮必须使用 CSV 读取**：\n"
        "```python\n"
        "import pandas as pd\n"
        "import matplotlib.pyplot as plt\n"
        "import seaborn as sns\n"
        "from pathlib import Path\n\n"
        "# ⚠️ 第2-6轮必须使用CSV文件路径\n"
        'CSV_PATH = r"/path/to/workspace/data/文件名.csv"  # 从上方列表复制\n'
        'OUTPUT_DIR = Path("generated")\n'
        "OUTPUT_DIR.mkdir(parents=True, exist_ok=True)\n\n"
        "# ✅ 必须使用 pd.read_csv() 读取\n"
        "df = pd.read_csv(CSV_PATH)\n\n"
        "# 保存 CSV\n"
        "summary = df.describe(include='all').transpose().reset_index()\n"
        "summary.to_csv(OUTPUT_DIR / '<表名>_summary.csv', index=False, encoding='utf-8')\n\n"
        "# 保存 PNG\n"
        "plt.figure(figsize=(6, 4))\n"
        "sns.countplot(x='<字段名>', data=df)\n"
        "plt.title('<表名> <字段名> distribution')\n"
        "plt.tight_layout()\n"
        "plt.savefig(OUTPUT_DIR / '<表名>_<字段名>_dist.png', dpi=120)\n"
        "plt.close()\n"
        "```\n\n"
        "**【代码模板 B】第 7 轮使用 SQLite 多表关联**：\n"
        "```python\n"
        "import sqlite3\n"
        "import pandas as pd\n"
        "import matplotlib.pyplot as plt\n"
        "from pathlib import Path\n\n"
        f'DB_PATH = r"{db_name}"\n'
        'OUTPUT_DIR = Path("generated")\n'
        "OUTPUT_DIR.mkdir(parents=True, exist_ok=True)\n\n"
        "with sqlite3.connect(DB_PATH, timeout=30) as conn:\n"
        '    conn.execute("PRAGMA busy_timeout = 30000;")\n'
        '    df = pd.read_sql_query("SELECT * FROM <表名> LIMIT 1000", conn)\n'
        "```\n\n"
        f"⚠️ **第2-6轮严禁使用SQLite,必须使用CSV读取**。\n"
    )

    file_block = "\n<File>\n暂无文件\n</File>\n"
    # Bootstrap只提供信息,不强制任务,让提示词自然引导
    return f"{block}{exe_block}{db_path_reminder}{file_block}"


def extract_effective_code(code_str: str) -> str:
    """若 <Code> 中包裹代码块/三引号，提取其中的实际脚本内容。"""
    if not code_str:
        return ""

    code = code_str.strip()

    # 兼容仍残留的 markdown 代码围栏
    fence_match = re.match(r"^```(?:[\w+-]+)?\s*(.*?)\s*```$", code, re.DOTALL)
    if fence_match:
        code = fence_match.group(1).strip()
    elif code.endswith("```"):
        code = re.sub(r"```[\t ]*$", "", code).rstrip()

    for quote in ('"""', "'''"):
        start = code.find(quote)
        if start != -1:
            end = code.find(quote, start + 3)
            if end != -1:
                before = code[:start].strip()
                after = code[end + 3 :].strip()
                inner = code[start + 3 : end].strip()
                # 仅当整段代码完全被三引号包裹时，才返回内部脚本
                if (
                    not before
                    and not after
                    and any(
                        token in inner
                        for token in ["import", "select", "plt.", "sns.", "pd."]
                    )
                ):
                    return inner

    # 若 <Code> 开头仍残留自然语言描述，则截取到首个 Python 语句
    python_start = re.search(
        r"(?m)^\s*(?:import\s+\w|from\s+\w+\s+import|#!/usr/bin/env\s+python)",
        code,
    )
    if python_start and python_start.start() > 0:
        code = code[python_start.start() :].lstrip()
    return code


def bot_stream(messages, workspace, session_id="default"):
    original_cwd = os.getcwd()
    workspace_path = Path(get_session_workspace(session_id)).resolve()
    workspace_path.mkdir(parents=True, exist_ok=True)
    ensure_default_sqlite(workspace_path)
    generated_dir = workspace_path / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    reset_stop_flag(session_id)

    if messages and messages[0]["role"] == "assistant":
        messages = messages[1:]

    workspace_file_info = ""
    tracked_paths: set[str] = set()
    if isinstance(workspace, list) and workspace:
        workspace_file_info = format_workspace_payload(workspace)
        for entry in workspace:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            if not name:
                continue
            tracked_paths.add(str((workspace_path / name).resolve()))
    elif isinstance(workspace, str) and workspace:
        workspace_file_info = collect_file_info(workspace)
        tracked_paths = snapshot_workspace_files(workspace)
    else:
        workspace_file_info = collect_file_info(str(workspace_path))
        tracked_paths = snapshot_workspace_files(str(workspace_path))

    if messages and messages[-1]["role"] == "user":
        user_message = messages[-1]["content"]
        if workspace_file_info:
            messages[-1][
                "content"
            ] = f"# Instruction\n{user_message}\n\n# Data\n{workspace_file_info}"
        else:
            messages[-1]["content"] = f"# Instruction\n{user_message}"

    initial_workspace = set(tracked_paths)
    assistant_reply = ""
    finished = False
    exe_output = None
    iteration = 0
    raw_iterations = 0
    max_raw_iterations = MAX_ITERATIONS * 2
    empty_retry = 0
    forced_reason = ""
    stop_requested = False

    last_code_signature = None
    last_analyze_signature = None
    last_execute_signature = None
    schema_confirmed = False
    schema_only_repeat = 0
    execute_rounds = 0
    non_schema_exec_rounds = 0
    answer_requested = False
    answer_waiting_rounds = 0
    premature_answer_rounds = 0
    empty_code_rounds = 0  # 连续无有效代码的轮数
    MAX_EMPTY_CODE_ROUNDS = 3
    missing_code_rounds = 0  # 连续缺少 <Code> 标签的轮数
    MAX_MISSING_CODE_ROUNDS = 3
    duplicate_analyze_rounds = 0  # 连续重复 <Analyze> 的轮数
    MAX_DUPLICATE_ANALYZE_ROUNDS = 5  # 最多允许 5 轮重复（增加容忍度）
    suppress_duplicate_analyze_once = (
        False  # 遇到可重试错误时，允许下一轮重复 <Analyze>
    )

    def allow_duplicate_analyze_retry():
        """标记下一轮允许重复 <Analyze>（通常用于同一轮的纠错重试）。"""
        nonlocal suppress_duplicate_analyze_once
        suppress_duplicate_analyze_once = True

    baseline_tables = list_sqlite_tables(workspace_path)
    known_tables = set(baseline_tables)
    initial_tables_locked = bool(known_tables)
    recent_tables_used: set[str] = set()
    schema_summary_injected = False
    schema_bootstrap_used = False
    unknown_table_warnings: set[str] = set()  # 跟踪已警告的未知表名,防止重复警告
    rule_for_next = None  # 初始化 rule_for_next，避免在表名检测时出现 UnboundLocalError

    def append_user_prompt(prompt_text: str) -> bool:
        """向 messages 追加 user 提示，并对相邻重复提示做去重，避免前端刷屏。"""
        if not prompt_text:
            return False
        if messages:
            last = messages[-1]
            if (
                isinstance(last, dict)
                and last.get("role") == "user"
                and str(last.get("content") or "") == str(prompt_text)
            ):
                logger.info(
                    "[bot_stream] Skip duplicate user prompt injection: %.120s",
                    str(prompt_text).replace("\n", " ")[:120],
                )
                return False
        messages.append({"role": "user", "content": prompt_text})
        return True

    def refund_iteration():
        nonlocal iteration
        iteration = max(0, iteration - 1)

    def refund_round_progress(is_schema_round: bool):
        """在执行失败或被退票时，回滚 execute_rounds / non_schema_exec_rounds 计数。"""
        nonlocal execute_rounds, non_schema_exec_rounds
        min_rounds = 1 if schema_bootstrap_used else 0
        if execute_rounds > min_rounds:
            execute_rounds -= 1
        if not is_schema_round and non_schema_exec_rounds > 0:
            non_schema_exec_rounds -= 1

    def ensure_known_tables(latest: set[str]):
        nonlocal known_tables, initial_tables_locked
        if initial_tables_locked:
            return
        if latest:
            known_tables = set(latest)
            initial_tables_locked = True

    def trim_messages(input_messages: list[dict]) -> list[dict]:
        serialized = "\n".join(
            json.dumps(m, ensure_ascii=False) for m in input_messages
        )
        if len(serialized) <= MAX_PROMPT_CHARS:
            return input_messages
        trimmed: list[dict] = []
        total = 0
        for msg in reversed(input_messages):
            encoded = json.dumps(msg, ensure_ascii=False)
            if total + len(encoded) > MAX_PROMPT_CHARS:
                break
            trimmed.append(msg)
            total += len(encoded)
        trimmed = list(reversed(trimmed))
        lead = [
            {
                "role": "system",
                "content": "历史消息过长，已截断早期对话，请根据仍保留的内容继续。",
            }
        ]
        return lead + trimmed

    # 【强制首轮 bootstrap】在第一轮迭代前，无论如何都先执行 schema bootstrap
    if not schema_bootstrap_used:
        logger.info(f"[bot_stream] Forcing schema bootstrap for session={session_id}")
        auto_block = run_schema_bootstrap(workspace_path, session_id)
        if auto_block:
            schema_bootstrap_used = True
            schema_confirmed = True
            # 将 bootstrap 结果注入到消息中，作为 assistant 的首轮输出
            messages.append({"role": "assistant", "content": auto_block})
            assistant_reply = auto_block
            yield auto_block
            # Bootstrap 算作 execute_round_0，所以下一轮应该是 round 1
            execute_rounds = 1
            logger.info(
                f"[bot_stream] Schema bootstrap completed, injected into messages, execute_rounds={execute_rounds}"
            )

    while (
        not finished
        and iteration < MAX_ITERATIONS
        and raw_iterations < max_raw_iterations
    ):
        raw_iterations += 1
        iteration += 1
        current_round = execute_rounds + 1
        premature_answer_detected = False
        rule_for_current_round = get_round_rule(current_round)
        mode_for_current_round = round_mode(rule_for_current_round)
        logger.info(
            f"[bot_stream] session={session_id} iteration={iteration} raw={raw_iterations} starting, messages={len(messages)}"
        )
        safe_messages = trim_messages(messages)

        response = client.chat.completions.create(
            model=MODEL_PATH,
            messages=safe_messages,
            temperature=0.3,
            stream=True,
            extra_body={
                "add_generation_prompt": False,
                "stop_token_ids": [151676, 151645],
                "max_new_tokens": 4096,
            },
        )
        raw_res = ""
        sanitized_stream = ""
        claimed_files_in_round: set[str] = set()
        last_finish_reason = None
        code_executed = False
        MAX_STREAM_LENGTH = (
            12000 if mode_for_current_round == "final_answer" else 50000
        )  # 最大流式输出长度
        repetition_check_window = ""  # 用于检测重复内容
        stream_forced_abort = False  # 流式阶段强制终止后，避免进入后置解析导致重复重试
        try:
            chunk_index = 0
            for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content is not None:
                    delta = chunk.choices[0].delta.content
                    raw_res += delta
                    chunk_index += 1
                    if chunk_index <= 5:
                        logger.info(
                            f"[bot_stream] Received chunk #{chunk_index}, delta_len={len(delta)}, raw_total={len(raw_res)}"
                        )

                    # 检测流式输出长度是否超限
                    if len(raw_res) > MAX_STREAM_LENGTH:
                        logger.warning(
                            f"[bot_stream] Stream length exceeded {MAX_STREAM_LENGTH}, forcing stop"
                        )
                        forced_reason = f"模型输出超过 {MAX_STREAM_LENGTH} 字符，疑似陷入重复循环，已强制终止。请检查提示词或重新发起会话。"
                        error_block = f"\n<Answer>\n{forced_reason}\n</Answer>\n"
                        assistant_reply += error_block
                        yield error_block
                        finished = True
                        stream_forced_abort = True
                        break

                    # 流式阶段只做标签归一化，不过滤 <File> 标签（避免截断未闭合的标签）
                    normalized_stream = normalize_model_tags(raw_res)
                    new_segment = normalized_stream[len(sanitized_stream) :]

                    # 流式输出正常，无需调试日志

                    if new_segment:
                        # 检测重复内容（最近 500 字符）
                        repetition_check_window += new_segment
                        if len(repetition_check_window) > 500:
                            repetition_check_window = repetition_check_window[-500:]
                        # 如果最近 500 字符中有超过 80% 是相同的字符（如 --），则判定为重复
                        if len(repetition_check_window) >= 100:
                            char_counts = {}
                            for char in repetition_check_window:
                                # 检测重复的分隔符、空白符和数字
                                if char in (
                                    "-",
                                    "=",
                                    "_",
                                    "*",
                                    "\n",
                                    " ",
                                    "0",
                                    "1",
                                    "2",
                                    "3",
                                    "4",
                                    "5",
                                    "6",
                                    "7",
                                    "8",
                                    "9",
                                ):
                                    char_counts[char] = char_counts.get(char, 0) + 1
                            max_count = max(char_counts.values()) if char_counts else 0
                            if max_count > len(repetition_check_window) * 0.8:
                                logger.warning(
                                    f"[bot_stream] Detected repetitive output (char '{max(char_counts, key=char_counts.get)}' appears {max_count} times in {len(repetition_check_window)} chars)"
                                )
                                forced_reason = "检测到模型输出重复内容（如连续分隔线），已强制终止。请检查提示词或重新发起会话。"
                                error_block = (
                                    f"\n<Answer>\n{forced_reason}\n</Answer>\n"
                                )
                                assistant_reply += error_block
                                yield error_block
                                finished = True
                                stream_forced_abort = True
                                break

                        assistant_reply += new_segment
                        yield new_segment
                        sanitized_stream = normalized_stream
                if chunk.choices and chunk.choices[0].finish_reason:
                    last_finish_reason = chunk.choices[0].finish_reason
                if should_stop(session_id):
                    stop_msg = "\n<Execute>\n```\n检测到停止指令，本轮生成已中断（未推进轮次）。\n```\n</Execute>\n"
                    assistant_reply += stop_msg
                    yield stop_msg
                    stop_requested = True
                    reset_stop_flag(session_id)
                    break
                current_stream = sanitized_stream

                # 【重要】先检查 </Answer>，再检查 </Code>，避免提前 break 导致拦截失效
                if "</Answer>" in current_stream:
                    if mode_for_current_round != "final_answer":
                        premature_answer_rounds += 1
                        messages.append(
                            {"role": "assistant", "content": current_stream}
                        )
                        warn_msg = (
                            "⚠️ 检测到你输出了 <Answer>，但当前轮次并非最终总结轮。\n\n"
                            f"当前轮次：第 {current_round} 轮（mode={mode_for_current_round or 'unknown'}）。\n"
                            "请继续按系统要求输出 <Analyze> + <Code> 完成本轮任务，禁止提前输出 <Answer>。"
                        )
                        messages.append({"role": "user", "content": warn_msg})
                        current_stream = current_stream.replace(
                            "<Answer>", "<Answer (ignored)>"
                        )
                        sanitized_stream = current_stream
                        premature_answer_detected = True
                        if premature_answer_rounds >= 3:
                            forced_reason = "连续 3 次在非 final_answer 轮次输出 <Answer>，任务被终止"
                            finished = True
                            break
                    else:
                        finished = True
                        break

                # 检测到 </Code> 标签时立即停止流式接收，防止模型在 </Code> 后继续输出
                if "</Code>" in current_stream:
                    logger.info(
                        f"[bot_stream] Detected </Code>, stopping stream reception"
                    )
                    break
        except Exception as stream_error:
            error_block = (
                "\n<Answer>\n"
                "底层模型在流式输出过程中断或超时，当前对话被迫结束。"
                f" 具体错误：{stream_error}。请检查模型服务日志，确认 {MODEL_PATH} 是否仍在运行且网络连通，"
                "然后重新发起任务。若模型端无异常，也可尝试在 config 中增加 timeout。\n</Answer>\n"
            )
            forced_reason = "模型流式输出失败"
            assistant_reply += error_block
            yield error_block
            finished = True  # 标记为完成，继续执行后续的报告生成逻辑
            break

        # 若流式阶段已经强制终止（超长/重复），直接结束本次请求，避免进入后置解析触发 refund_iteration 导致重复输出。
        if stream_forced_abort:
            return

        if premature_answer_detected and not finished:
            refund_iteration()
            continue

        claimed_files_in_round: set[str] = set()
        file_claim_warning_sent = False

        def emit_file_claim_warning(reason: str) -> str:
            nonlocal file_claim_warning_sent
            if file_claim_warning_sent or not claimed_files_in_round:
                return ""
            names = ", ".join(sorted(claimed_files_in_round))
            detail = f"原因：{reason}。" if reason else ""
            file_claim_warning_sent = True
            return (
                "\n<Analyze>\n"
                "系统检测到你在 <File> 中声明了以下文件："
                + names
                + f"。{detail}本轮脚本尚未执行或已被退票，这些链接没有对应的真实文件。"
                "请等待系统执行成功后，由系统自动输出真实的 <File> 段，勿手动伪造。\n"
                "</Analyze>\n"
            )

        try:
            cur_res = normalize_model_tags(raw_res)
            claimed_files_in_round = extract_file_claims(cur_res)

            logger.info(
                f"[bot_stream] Before strip_model_file_blocks: raw_res length={len(raw_res)}, cur_res length={len(cur_res)}, has_<File>={'<File>' in cur_res}, has_</File>={'</File>' in cur_res}"
            )

            # 先检测伪造 Execute（在 strip 之前检测原始输出）
            has_execute_in_raw = "<Execute>" in cur_res

            cur_res = strip_model_file_blocks(cur_res)

            # 调试日志：记录处理后的内容
            logger.info(
                f"[bot_stream] After normalization, cur_res length={len(cur_res)}, has_<Code>={'<Code>' in cur_res}, has_</Code>={'</Code>' in cur_res}, had_<Execute>_in_raw={has_execute_in_raw}"
            )

            fixed_res = fix_tags_and_codeblock(cur_res)
            if fixed_res != cur_res:
                extra_text = fixed_res[len(cur_res) :]
                if extra_text:
                    assistant_reply += extra_text
                    yield extra_text
                cur_res = fixed_res

            logger.info(
                f"[bot_stream] session={session_id} iteration={iteration} finish_reason={last_finish_reason} has_code={'<Code>' in cur_res} closed={'</Code>' in cur_res} len={len(cur_res)}"
            )

            # 【空响应检测】必须在所有其他检测之前执行
            # 这样可以避免空响应被计入有效迭代，导致模型在下一轮复制提示词模板
            if not cur_res.strip() and not finished:
                empty_retry += 1
                logger.warning(
                    f"[bot_stream] Empty response detected (retry {empty_retry}/3)"
                )
                if empty_retry < 3:
                    next_round = execute_rounds + 1
                    retry_prompt = build_round_retry_prompt(next_round, empty_retry)
                    messages.append({"role": "user", "content": retry_prompt})
                    refund_iteration()  # 关键：退还迭代计数
                    continue
                forced_reason = "连续 3 轮输出为空，已终止任务"
                finished = True
                break
            else:
                empty_retry = 0

            analyze_match = re.search(r"<Analyze>(.*?)</Analyze>", cur_res, re.DOTALL)
            analyze_content = analyze_match.group(1).strip() if analyze_match else ""
            analyze_signature = (
                re.sub(r"\s+", " ", analyze_content) if analyze_content else ""
            )

            rule_for_next = get_round_rule(current_round)
            mode_for_next = round_mode(rule_for_next)

            if mode_for_next == "final_answer":
                if (
                    "<Code>" in cur_res
                    or "</Code>" in cur_res
                    or "<Analyze>" in cur_res
                ):
                    logger.warning(
                        "[bot_stream] Code rejected: final_answer round must not include <Analyze>/<Code>"
                    )
                    messages.append({"role": "assistant", "content": cur_res})
                    prompt = (
                        f"第 {current_round} 轮为 final_answer：只允许输出单个 <Answer>，"
                        "禁止出现 <Analyze>/<Code>，也禁止输出 schema/sql 代码块。"
                        "请立即改为只输出：\n\n"
                        "<Answer>\n...\n</Answer>"
                    )
                    messages.append({"role": "user", "content": prompt})
                    refund_iteration()
                    continue
                if "<Answer>" not in cur_res or "</Answer>" not in cur_res:
                    logger.warning(
                        "[bot_stream] Code rejected: final_answer round missing <Answer> block"
                    )
                    messages.append({"role": "assistant", "content": cur_res})
                    prompt = (
                        f"第 {current_round} 轮为 final_answer：必须输出单个完整 <Answer>...</Answer>，"
                        "不要输出其他内容。请立即补全并确保闭合 </Answer>。"
                    )
                    messages.append({"role": "user", "content": prompt})
                    refund_iteration()
                    continue
                finished = True
                break

            # 记录 analyze_signature 用于调试重复检测
            logger.info(
                f"[bot_stream] session={session_id} iteration={iteration} "
                f"analyze_signature={analyze_signature[:200]} "
                f"last_signature={last_analyze_signature[:200] if last_analyze_signature else 'None'}"
            )

            # 【关键】在所有拦截逻辑之前检测重复 <Analyze>
            # 这样可以在模型被拦截并 refund_iteration 后，下次循环时检测到重复
            if last_analyze_signature and analyze_signature == last_analyze_signature:
                if suppress_duplicate_analyze_once:
                    logger.info(
                        f"[bot_stream] session={session_id} iteration={iteration} "
                        "Duplicate <Analyze> tolerated once due to pending retry"
                    )
                    suppress_duplicate_analyze_once = False
                    duplicate_analyze_rounds = 0
                else:
                    duplicate_analyze_rounds += 1
                    logger.warning(
                        f"[bot_stream] session={session_id} iteration={iteration} "
                        f"Detected duplicate <Analyze> signature (round {duplicate_analyze_rounds}/{MAX_DUPLICATE_ANALYZE_ROUNDS}): "
                        f"{analyze_signature[:100]}"
                    )

                    if duplicate_analyze_rounds >= MAX_DUPLICATE_ANALYZE_ROUNDS:
                        forced_reason = (
                            f"连续 {MAX_DUPLICATE_ANALYZE_ROUNDS} 轮输出相同的 <Analyze> 内容，"
                            "系统判定模型陷入重复循环，强制终止任务。"
                        )
                        violation_block = f"\n<Answer>\n{forced_reason}\n</Answer>\n"
                        assistant_reply += violation_block
                        yield violation_block
                        logger.error(
                            f"[bot_stream] session={session_id} Force terminated due to duplicate <Analyze>"
                        )
                        return

                    messages.append({"role": "assistant", "content": cur_res})
                    diff_prompt = (
                        f"【警告】你的 <Analyze> 内容与上一轮完全相同（已连续 {duplicate_analyze_rounds} 轮）。\n\n"
                        "请立即采取以下行动之一：\n"
                        "1. 如果已完成所有分析，直接输出 <Answer> 总结结论（包含 2+ 条定量发现和后续建议）\n"
                        "2. 如果还需继续分析，必须提出**完全不同**的分析目标（例如：分析其他表、其他字段、不同维度的聚合等）\n\n"
                        "禁止重复相同的分析步骤。"
                    )
                    messages.append({"role": "user", "content": diff_prompt})
                    refund_iteration()
                    continue
            else:
                duplicate_analyze_rounds = 0
                suppress_duplicate_analyze_once = False

            # 【关键】在所有拦截逻辑之前更新 last_analyze_signature
            # 这样即使后续逻辑 continue，下次循环也能检测到重复
            last_analyze_signature = analyze_signature

            if not analyze_content:
                messages.append({"role": "assistant", "content": cur_res})
                if (
                    not schema_confirmed
                    and not schema_bootstrap_used
                    and round_mode(rule_for_next) != "filesystem_summary"
                ):
                    auto_block = run_schema_bootstrap(workspace_path, session_id)
                    if auto_block:
                        schema_bootstrap_used = True
                        schema_confirmed = True
                        latest_tables = list_sqlite_tables(workspace_path)
                        ensure_known_tables(latest_tables)
                        assistant_reply += auto_block
                        yield auto_block
                        messages.append({"role": "assistant", "content": auto_block})
                        continue
                analyze_prompt = "你的输出缺少 <Analyze> 段，必须先在 <Analyze> 中说明当前目标与依据，再给出 <Code>。"
                messages.append({"role": "user", "content": analyze_prompt})
                refund_iteration()
                continue

            # 修复17: 移除这个判断,它会干扰正常的分析流程
            # 提示词已经明确规定了第2-6轮的分析流程,不应该让系统注入"请提出分析目标"
            # if (
            #     schema_confirmed
            #     and "列出" in analyze_content
            #     and "表结构" in analyze_content
            # ):
            #     messages.append({"role": "assistant", "content": cur_res})
            #     advance_prompt = "表结构已在首轮列出，请基于已知表/字段提出新的分析目标，换用真实查询或 EDA 任务。"
            #     messages.append({"role": "user", "content": advance_prompt})
            #     refund_iteration()
            #     continue

            known_mentions = set()
            unknown_mentions = set()
            require_known_reference = schema_confirmed

            # 获取当前轮次的模式（必须以当前轮为准，避免沿用上一轮）
            rule_for_current = get_round_rule(current_round)
            current_mode = round_mode(rule_for_current) if rule_for_current else None

            # CSV 分析/报告轮次跳过表名检测
            # 这些轮次的 <Analyze> 易包含字段/文件/变量名，可能被误识别为表名
            skip_table_check = current_mode in (
                "csv_analysis",
                "sqlite_join",
                "filesystem_summary",
                "html_report",
                "html_report_phase2",
            )

            logger.info(
                f"[bot_stream] Extracting table mentions: known_tables={len(known_tables)}, analyze_content_len={len(analyze_content)}, mode={current_mode}, skip={skip_table_check}"
            )
            if known_tables and not skip_table_check:
                try:
                    known_mentions, unknown_mentions = extract_table_mentions_from_text(
                        analyze_content, known_tables
                    )
                    logger.info(
                        f"[bot_stream] Table mentions extracted: known={known_mentions}, unknown={unknown_mentions}"
                    )
                except Exception as e:
                    logger.error(
                        f"[bot_stream] Error extracting table mentions: {e}",
                        exc_info=True,
                    )
                    known_mentions = set()
                    unknown_mentions = set()
                # 修复20: 防止重复警告导致无限循环
                if schema_confirmed and unknown_mentions:
                    new_unknown = unknown_mentions - unknown_table_warnings
                    if new_unknown:
                        unknown_table_warnings.update(new_unknown)
                        logger.info(
                            f"[bot_stream] Unknown table hints (Analyze only): {new_unknown}"
                        )
                        messages.append({"role": "assistant", "content": cur_res})
                        warn_unknown = (
                            "检测到你在 <Analyze> 中提到了未出现在 sqlite_master 的名称："
                            + ", ".join(sorted(new_unknown))
                            + "。如果这是文件/字段/图表名称，请忽略此提示；若确实是表名，请参考首轮 sqlite_master 结果，仅使用真实表名。"
                        )
                        messages.append({"role": "user", "content": warn_unknown})
                        refund_iteration()
                        continue
                # Analyze 文本仅用于提示，不再强制要求含已知表名

            if finished:
                # 检查是否提前输出 Answer（在完成足够轮次之前）
                MIN_REQUIRED_ROUNDS = (
                    9  # 至少需要 9 轮（确保第 8、9 轮的 HTML 报告都已生成）
                )
                if execute_rounds < MIN_REQUIRED_ROUNDS:
                    logger.warning(
                        f"[bot_stream] Premature <Answer> detected: execute_rounds={execute_rounds}, required={MIN_REQUIRED_ROUNDS}"
                    )
                    messages.append({"role": "assistant", "content": cur_res})
                    reject_msg = (
                        f"⚠️ 检测到提前终止：当前仅完成 {execute_rounds} 轮分析，但任务要求完成至少 {MIN_REQUIRED_ROUNDS} 轮。\n\n"
                        "**必须继续执行以下轮次**：\n"
                        "- 第 2-6 轮：单表分析（处理多个数据文件）\n"
                        "- 第 7 轮：多表关联分析\n"
                        "- 第 8 轮：生成 README.md 索引文件\n"
                        "- 第 9 轮：生成 multi_table_analysis.html 汇总报告\n"
                        "- 第 10 轮：输出最终 <Answer>\n\n"
                        f"**请立即继续第 {execute_rounds + 1} 轮分析，禁止输出 <Answer>。**"
                    )
                    messages.append({"role": "user", "content": reject_msg})
                    refund_iteration()
                    finished = False
                    continue

                logger.info(f"[bot_stream] Finished flag detected, breaking loop")
                break

            # 修复：模型可能输出了 <Code> 但遗漏 </Code>，导致被误判为缺少 Code block 并触发强制终止。
            # 必须在 has_code_block 校验前进行补齐。
            if last_finish_reason in {"stop", "length"}:
                if "<Code>" in cur_res and "</Code>" not in cur_res:
                    cur_res += "</Code>"
                    logger.info(
                        "[bot_stream] Auto-closed missing </Code> before validation"
                    )
                if "<File>" in cur_res and "</File>" not in cur_res:
                    cur_res = cur_res.split("<File>")[0]

                # 防御：部分模型会在 </Code> 之后继续输出“schema / Code / sql”块（常见为重复提示或虚构表结构）
                # 这类内容会污染消息历史并导致后续轮次输出膨胀。
                schema_tail = re.search(
                    r"\n\s*schema\s*\n\s*Code\s*\n\s*sql\s*\n", cur_res, re.IGNORECASE
                )
                if schema_tail:
                    cur_res = cur_res[: schema_tail.start()].rstrip()

            # 容错：允许 <code>/<Code > 等大小写与空白差异；若只有 markdown 代码块但缺少 <Code>，自动包裹。
            normalized_res = cur_res
            normalized_res = re.sub(
                r"<\s*/\s*code\s*>", "</Code>", normalized_res, flags=re.IGNORECASE
            )
            normalized_res = re.sub(
                r"<\s*code\s*>", "<Code>", normalized_res, flags=re.IGNORECASE
            )
            if "<Code>" not in normalized_res and "```" in normalized_res:
                md_block = re.search(
                    r"```(?:python)?\s*(.*?)```", normalized_res, re.DOTALL
                )
                if md_block:
                    code_body = md_block.group(1).strip()
                    normalized_res = (
                        normalized_res + "\n<Code>\n" + code_body + "\n</Code>\n"
                    )
                    logger.info(
                        "[bot_stream] Wrapped fenced code block into <Code> for validation"
                    )

            # 兜底：有些模型会直接输出 Python 脚本但不带 <Code> 标签/``` 围栏。
            # 这种情况下 has_code_block=False 会触发反复重试，导致轮次/提示词错位与重复输出。
            if "<Code>" not in normalized_res:
                leading = normalized_res.lstrip()
                looks_like_python = bool(
                    re.match(
                        r"^(?:#!|from\s+\w+\s+import\s+|import\s+\w+)",
                        leading,
                    )
                )
                if looks_like_python:
                    normalized_res = f"<Code>\n{normalized_res.strip()}\n</Code>\n"
                    logger.info(
                        "[bot_stream] Wrapped raw python script into <Code> for validation"
                    )

            cur_res = normalized_res

            logger.info(f"[bot_stream] Checking for <Code> block in response")
            has_code_block = "<Code>" in cur_res and "</Code>" in cur_res
            logger.info(f"[bot_stream] has_code_block={has_code_block}")

            # 调试日志：检查 Code 标签检测
            if not has_code_block:
                logger.warning(
                    f"[bot_stream] No <Code> block detected. cur_res preview: {cur_res[:200]}"
                )

            if not has_code_block:
                messages.append({"role": "assistant", "content": cur_res})
                # 只有在达到最小轮次后才响应 answer_requested
                MIN_REQUIRED_ROUNDS = 9
                if answer_requested and execute_rounds >= MIN_REQUIRED_ROUNDS:
                    answer_waiting_rounds += 1
                    reminder = (
                        "你已完成必要的代码执行，请直接给出 <Answer>，总结 <Execute>/<File> 的发现并提出建议，"
                        "不要再给新的 <Analyze>/<Code>。"
                    )
                    messages.append({"role": "user", "content": reminder})
                    if answer_waiting_rounds >= 2:
                        violation_block = "\n<Answer>\n多次提醒后仍未输出 <Answer>，任务被终止。请使用现有结果自行总结或重新发起任务。\n</Answer>\n"
                        assistant_reply += violation_block
                        yield violation_block
                        return
                else:
                    missing_code_rounds += 1
                    logger.warning(
                        f"[bot_stream] Code block missing (round {missing_code_rounds}/{MAX_MISSING_CODE_ROUNDS})"
                    )
                    if missing_code_rounds >= MAX_MISSING_CODE_ROUNDS:
                        forced_reason = (
                            f"连续 {MAX_MISSING_CODE_ROUNDS} 轮未输出 <Code> 标签，"
                            "系统判定模型未遵守提示词约束（每轮必须包含 <Analyze> + <Code>），强制终止任务。"
                            "请检查提示词是否明确要求输出 <Code>，或重新发起会话。"
                        )
                        violation_block = f"\n<Answer>\n{forced_reason}\n</Answer>\n"
                        assistant_reply += violation_block
                        yield violation_block
                        return
                    # 修复19: 当execute_rounds=1(Bootstrap后)且缺少代码时,明确指导开始第2轮分析
                    if execute_rounds == 1:
                        rule_for_next = get_round_rule(execute_rounds + 1)
                        required_csv = (
                            round_input_filename(rule_for_next)
                            if rule_for_next
                            else None
                        )
                        csv_abs_path = ""
                        if required_csv:
                            csv_abs_path = str(
                                (Path(workspace_path) / "data" / required_csv).resolve()
                            )
                        code_prompt = (
                            "⚠️ Bootstrap已完成,禁止重复输出Bootstrap代码!\n\n"
                            "🚨 立即开始第2轮分析 - enrolled.csv 🚨\n\n"
                            "必须按照以下格式输出:\n\n"
                            "<Analyze>\n"
                            "第2轮任务:分析enrolled.csv文件,统计学校分布和月份分布\n"
                            "</Analyze>\n\n"
                            "<Code>\n"
                            "import pandas as pd\n"
                            "import matplotlib.pyplot as plt\n"
                            "import seaborn as sns\n"
                            "from pathlib import Path\n\n"
                            "# 读取enrolled.csv\n"
                            f"CSV_PATH = r'{csv_abs_path or '<请从首轮CSV路径列表复制>'}'\n"
                            "df = pd.read_csv(CSV_PATH)\n\n"
                            "# 生成enrolled_summary.csv\n"
                            "OUTPUT_DIR = Path('generated')\n"
                            "OUTPUT_DIR.mkdir(parents=True, exist_ok=True)\n"
                            "summary = df.describe(include='all').transpose().reset_index()\n"
                            "summary.to_csv(OUTPUT_DIR / 'enrolled_summary.csv', index=False, encoding='utf-8')\n\n"
                            "# 生成enrolled_school_dist.png\n"
                            "plt.figure(figsize=(10, 6))\n"
                            "sns.countplot(data=df, x='school')\n"
                            "plt.title('School Distribution')\n"
                            "plt.xticks(rotation=45)\n"
                            "plt.tight_layout()\n"
                            "plt.savefig(OUTPUT_DIR / 'enrolled_school_dist.png', dpi=120)\n"
                            "plt.close()\n"
                            "</Code>\n\n"
                            "请立即按照上述格式输出第2轮分析!"
                        )
                    else:
                        code_prompt = (
                            f"你的输出缺少 <Code> 段（已连续 {missing_code_rounds} 轮）。请在 <Analyze> 后立刻提供完整的 Python 代码（含 import/连接/EDA/plt 保存/conn.close()），"
                            "以便系统执行。参考提示词中的代码模板，必须输出 <Code>...</Code> 标签。"
                        )
                    messages.append({"role": "user", "content": code_prompt})
                refund_iteration()
                continue

            if last_finish_reason in {"stop", "length"} and not finished:
                if "<Code>" in cur_res and "</Code>" not in cur_res:
                    missing_tag = "</Code>"
                    cur_res += missing_tag
                    assistant_reply += missing_tag
                    yield missing_tag
                elif "<Code>" not in cur_res:
                    # 模型未输出 <Code>，向其追加纠错提示并进入下一轮
                    messages.append({"role": "assistant", "content": cur_res})
                    missing_code_rounds += 1
                    logger.warning(
                        f"[bot_stream] Code block missing (round {missing_code_rounds}/{MAX_MISSING_CODE_ROUNDS})"
                    )
                    if missing_code_rounds >= MAX_MISSING_CODE_ROUNDS:
                        forced_reason = (
                            f"连续 {MAX_MISSING_CODE_ROUNDS} 轮未输出 <Code> 标签，"
                            "系统判定模型未遵守提示词约束（每轮必须包含 <Analyze> + <Code>），强制终止任务。"
                            "请检查提示词是否明确要求输出 <Code>，或更换模型/重新发起会话。"
                        )
                        violation_block = f"\n<Answer>\n{forced_reason}\n</Answer>\n"
                        assistant_reply += violation_block
                        yield violation_block
                        return
                    correction_prompt = (
                        "你必须严格按如下结构输出：先用 <Analyze> 拆解任务，紧接着在 <Code> 中给出可执行的"
                        " Python 代码（使用 ```python ... ``` 包裹），等待系统执行，再结合 <Execute>/<File> 结果"
                        " 继续分析。不要重复欢迎语，立刻补充缺失的 <Code>。"
                    )
                    messages.append({"role": "user", "content": correction_prompt})
                    refund_iteration()
                    continue

            # 重置缺少 <Code> 的计数器
            missing_code_rounds = 0

            if "</Code>" in cur_res and not finished:
                # 只有在达到最小轮次后才响应 answer_requested
                MIN_REQUIRED_ROUNDS = 9
                if answer_requested and execute_rounds >= MIN_REQUIRED_ROUNDS:
                    messages.append({"role": "assistant", "content": cur_res})
                    reminder = "分析已完成，请停止输出新的 <Code>。在下一轮直接编写 <Answer>，总结已得到的 <Execute>/<File> 结果并给出进一步建议。"
                    messages.append({"role": "user", "content": reminder})
                    answer_waiting_rounds += 1
                    if answer_waiting_rounds >= 2:
                        violation_block = "\n<Answer>\n多次提醒后仍未输出 <Answer>，任务被自动终止。请使用现有 <Execute>/<File> 结果手动总结或重新发起指令。\n</Answer>\n"
                        assistant_reply += violation_block
                        yield violation_block
                        return
                    continue
                messages.append(
                    {
                        "role": "assistant",
                        "content": strip_model_file_blocks(cur_res),
                    }
                )
                code_match = re.search(r"<Code>(.*?)</Code>", cur_res, re.DOTALL)
                logger.info(f"[bot_stream] Code match result: {code_match is not None}")
                if code_match:
                    code_content = code_match.group(1).strip()
                    logger.info(
                        f"[bot_stream] Code content extracted, length={len(code_content)}"
                    )
                    # 修复21: 改进markdown代码块提取逻辑
                    # 如果代码以```python或```开头,去除markdown标记
                    if code_content.startswith("```"):
                        # 找到第一个换行符,去除```python或```行
                        first_newline = code_content.find("\n")
                        if first_newline != -1:
                            code_content = code_content[first_newline + 1 :]
                        # 去除末尾可能带空白的```标记
                        code_content = re.sub(r"```[\t ]*$", "", code_content.rstrip())
                        code_str = code_content.strip()
                    else:
                        # 尝试使用正则提取(兼容旧格式)
                        md_match = re.search(
                            r"```(?:python)?(.*?)```", code_content, re.DOTALL
                        )
                        code_str = (
                            md_match.group(1).strip() if md_match else code_content
                        )
                    effective_code = extract_effective_code(code_str)
                    # 额外清理：模型有时会把 Markdown 代码围栏 ``` / ```python 夹进 <Code> 中
                    # 这会在执行阶段触发 SyntaxError: invalid syntax，导致反复重试/重复输出。
                    if effective_code and "```" in effective_code:
                        cleaned_lines: list[str] = []
                        for line in effective_code.splitlines():
                            stripped = line.strip()
                            if stripped.startswith("```"):
                                continue
                            cleaned_lines.append(line)
                        effective_code = "\n".join(cleaned_lines).strip()
                    logger.info(
                        f"[bot_stream] Effective code extracted, length={len(effective_code) if effective_code else 0}"
                    )

                    # 防御：模型偶发把对话标签残片（如 </Analyze>）混入 <Code>，会导致执行阶段把标签当 Python 运行
                    # 这里仅拦截“看起来就是标签行”的情况，避免误伤正常的 HTML 字符串内容。
                    if effective_code:
                        suspicious_tag_lines = []
                        for line in effective_code.splitlines()[:8]:
                            stripped = line.strip()
                            if stripped in {
                                "<Analyze>",
                                "</Analyze>",
                                "<Code>",
                                "</Code>",
                                "<Answer>",
                                "</Answer>",
                            }:
                                suspicious_tag_lines.append(stripped)
                        if suspicious_tag_lines:
                            logger.warning(
                                "[bot_stream] Code rejected: detected conversation tag residues in <Code>: %s",
                                ", ".join(suspicious_tag_lines),
                            )
                            tag_prompt = (
                                "检测到你在 <Code> 中混入了对话标签（例如 </Analyze>）。"
                                "这会导致系统把标签当成 Python 执行并报错。"
                                "请只在 <Code> 中输出纯 Python 脚本（从 import 开始），不要包含任何 <Analyze>/<Code>/<Answer> 标签文本。"
                            )
                            messages.append({"role": "user", "content": tag_prompt})
                            refund_iteration()
                            continue

                    # 检测连续无有效代码
                    if not effective_code or not effective_code.strip():
                        logger.warning(
                            f"[bot_stream] Code rejected: empty effective code"
                        )
                        empty_code_rounds += 1
                        if empty_code_rounds >= MAX_EMPTY_CODE_ROUNDS:
                            forced_reason = (
                                f"连续 {MAX_EMPTY_CODE_ROUNDS} 轮未输出有效 <Code>，"
                                "系统判定模型未遵守提示词约束（每轮必须包含完整可运行脚本），强制终止任务。"
                                "请检查提示词是否明确要求在 <Code> 中输出完整代码，或重新发起会话。"
                            )
                            violation_block = (
                                f"\n<Answer>\n{forced_reason}\n</Answer>\n"
                            )
                            assistant_reply += violation_block
                            yield violation_block
                            return
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    f"你的 <Code> 块为空或无有效内容（已连续 {empty_code_rounds} 轮）。"
                                    "请在 <Code> 中提供完整的 Python 脚本，包含 import、数据库连接、查询/分析逻辑、"
                                    "以及 plt.savefig/DataFrame.to_csv 等文件写入语句。参考提示词中的代码模板。"
                                ),
                            }
                        )
                        refund_iteration()
                        continue
                    else:
                        empty_code_rounds = 0  # 重置计数

                    target_round = execute_rounds + 1
                    rule_for_next = get_round_rule(target_round)
                    mode_for_next = round_mode(rule_for_next)

                    if mode_for_next in ("html_report", "html_report_phase2"):
                        expected_html_files = (
                            round_expected_filenames_by_type(rule_for_next, "html")
                            if rule_for_next
                            else []
                        )
                        if (
                            expected_html_files
                            and "html_lines" in effective_code
                            and "# AUTO_WRITE_HTML" not in effective_code
                        ):
                            html_name = expected_html_files[0]
                            auto_write_block = (
                                "\n\n# AUTO_WRITE_HTML\n"
                                "try:\n"
                                '    output_dir = Path("generated")\n'
                                "    output_dir.mkdir(parents=True, exist_ok=True)\n"
                                f'    html_path = output_dir / "{html_name}"\n'
                                '    html_path.write_text("\\n".join(html_lines), encoding="utf-8")\n'
                                f'    print("✅ {html_name} 已写入")\n'
                                "except Exception as err:\n"
                                '    print(f"⚠️ 自动写入 HTML 失败: {err}")\n'
                            )
                            effective_code = f"{effective_code}{auto_write_block}"

                        # 规则驱动校验：需要生成 HTML 时，代码中必须显式写入预期文件名。
                        # 防止模型把第10轮写成 multi_table_analysis.html 或写成 execute_round_10.txt。
                        if expected_html_files and expected_html_files[0]:
                            expected_html_name = expected_html_files[0]
                            if expected_html_name.lower() not in effective_code.lower():
                                logger.warning(
                                    "[bot_stream] Code rejected: expected HTML filename not referenced: %s",
                                    expected_html_name,
                                )
                                prompt = (
                                    f"第 {target_round} 轮必须写出 `{expected_html_name}`。"
                                    "请在代码中使用 `Path('generated') / '<文件名>'` 写入该 HTML 文件（必须与规则一致），"
                                    "不要写成其它 HTML 文件名，也不要写 execute_round_*.txt（该日志由系统自动生成）。"
                                )
                                messages.append({"role": "user", "content": prompt})
                                refund_iteration()
                                continue

                    # 拦截 HTML/前端模板被误当作 Python 代码的情况
                    # 只拒绝以 HTML 标签开头的代码（直接输出 HTML），允许包含 HTML 字符串的 Python 代码
                    first_line = (
                        effective_code.strip().split("\n")[0]
                        if effective_code.strip()
                        else ""
                    )
                    if re.match(
                        r"^\s*<!doctype html|^\s*<(html|head|body|section|div)\b",
                        first_line,
                        re.IGNORECASE,
                    ):
                        logger.warning(
                            "[bot_stream] Code rejected: detected HTML content instead of Python script"
                        )
                        html_prompt = (
                            "检测到你在 <Code> 中输出了 HTML 模板，但系统需要的是 Python 脚本。"
                            " 请提供可执行的 Python 代码（以生成 README.md/CSV/PNG 等文件），不要直接输出 HTML 页面内容。"
                        )
                        messages.append({"role": "user", "content": html_prompt})
                        refund_iteration()
                        continue

                    # 计算代码签名，用于重复检测
                    code_signature = "\n".join(
                        line.strip() for line in effective_code.splitlines()
                    ).strip()
                    normalized_code = effective_code.lower()

                    # 优先检测重复代码，避免无限循环
                    logger.info(
                        f"[bot_stream] Code signature check: current={code_signature[:50] if code_signature else 'None'}..., last={last_code_signature[:50] if last_code_signature else 'None'}..."
                    )
                    if code_signature and code_signature == last_code_signature:
                        logger.warning(f"[bot_stream] Code rejected: duplicate code")
                        reminder = (
                            "你的代码与上一轮完全相同。请根据已获取的表结构推进新的分析，"
                            "不要重复列出 sqlite_master。如果上一轮代码被拦截，请仔细阅读系统提示并修正问题。"
                        )
                        messages.append({"role": "user", "content": reminder})
                        refund_iteration()
                        continue

                    # 检查代码是否包含必要的导入（根据代码类型判断）
                    # CSV读取代码需要pandas,SQLite代码需要sqlite3
                    has_pandas = (
                        "import pandas" in effective_code
                        or "import pd" in effective_code
                    )
                    has_sqlite3 = "import sqlite3" in effective_code
                    uses_csv = (
                        "pd.read_csv" in effective_code
                        or "pandas.read_csv" in effective_code
                    )
                    uses_sqlite = (
                        "sqlite3.connect" in effective_code
                        or "pd.read_sql" in effective_code
                    )

                    # 如果使用CSV但没有导入pandas,或使用SQLite但没有导入sqlite3,则拒绝
                    if uses_csv and not has_pandas:
                        logger.warning(
                            f"[bot_stream] Code rejected: CSV code missing pandas import"
                        )
                        messages.append(
                            {
                                "role": "user",
                                "content": "你的代码使用了 `pd.read_csv()` 但缺少 `import pandas as pd`。请添加必要的导入语句。",
                            }
                        )
                        refund_iteration()
                        continue

                    if uses_sqlite and not has_sqlite3:
                        logger.warning(
                            f"[bot_stream] Code rejected: SQLite code missing sqlite3 import"
                        )
                        messages.append(
                            {
                                "role": "user",
                                "content": "你的代码使用了 `sqlite3.connect()` 但缺少 `import sqlite3`。请添加必要的导入语句。",
                            }
                        )
                        refund_iteration()
                        continue

                    if mode_for_next == "html_report_phase2":
                        uses_sqlite_master = "sqlite_master" in normalized_code
                        if uses_sqlite or uses_sqlite_master:
                            logger.warning(
                                "[bot_stream] Code rejected: html_report_phase2 should not execute SQLite"
                            )
                            sqlite_block_prompt = (
                                f"第 {target_round} 轮仅允许读取 generated/ 目录下的 CSV/PNG/README/HTML，"
                                "禁止使用 sqlite3.connect()/pd.read_sql() 访问 SQLite，也禁止查询 sqlite_master。"
                                "请改为用 pd.read_csv() 读取 generated/ 下真实存在的 CSV（至少包含 multi_table_join_result.csv），"
                                "再生成综合 HTML 报告写入 generated/。"
                            )
                            append_user_prompt(sqlite_block_prompt)
                            refund_iteration()
                            continue

                        if not uses_csv:
                            logger.warning(
                                "[bot_stream] Code rejected: html_report_phase2 must read generated CSV"
                            )
                            csv_prompt = (
                                f"第 {target_round} 轮必须用 pd.read_csv() 读取 generated/ 下真实存在的 CSV（至少 multi_table_join_result.csv），"
                                "禁止跳过读盘或只读取 execute_round_*.txt。请先读取 CSV 获取真实列名与统计，再生成综合 HTML 报告。"
                            )
                            append_user_prompt(csv_prompt)
                            refund_iteration()
                            continue

                        # 规则驱动约束：综合报告必须以 join 结果为主（提示词要求至少读取 multi_table_join_result.csv）。
                        # 避免模型错误地把所有 CSV 混合在一起导致列名臆测、类型冲突或报错并陷入循环。
                        if "multi_table_join_result.csv" not in effective_code.lower():
                            logger.warning(
                                "[bot_stream] Code rejected: html_report_phase2 must read multi_table_join_result.csv"
                            )
                            join_prompt = (
                                f"第 {target_round} 轮生成综合报告时，必须显式读取 `generated/multi_table_join_result.csv`（join 结果是综合分析的主数据）。"
                                "请先 `df = pd.read_csv(generated_dir / 'multi_table_join_result.csv')`，"
                                "基于 df 的真实列名/类型/行数/缺失情况与分布生成洞察，再写入 `generated/comprehensive_analysis_report.html`。"
                                "\n\n注意：不建议把 generated/ 下所有 CSV 直接 concat 混合分析（summary/join/count 等文件结构不同，会导致错误与不一致）。"
                            )
                            append_user_prompt(join_prompt)
                            refund_iteration()
                            continue

                        if "html_lines" not in normalized_code:
                            logger.warning(
                                "[bot_stream] Code rejected: html_report_phase2 must build html_lines"
                            )
                            html_lines_prompt = (
                                f"第 {target_round} 轮生成 HTML 时必须用 Python 构造 html_lines 列表逐行拼接，"
                                "并写入 generated/ 下规则要求的 HTML 文件；禁止直接 print 整段 HTML。"
                            )
                            append_user_prompt(html_lines_prompt)
                            refund_iteration()
                            continue

                        if '"""' in effective_code and "<html" in normalized_code:
                            logger.warning(
                                "[bot_stream] Code rejected: html_report_phase2 should not embed full HTML via triple quotes"
                            )
                            template_prompt = (
                                f'第 {target_round} 轮禁止使用三引号把整段 HTML 模板写死（例如 html = """<html>..."""）。'
                                "请改为使用 html_lines 列表逐行构造 HTML，再 write_text 写入 generated/。"
                            )
                            append_user_prompt(template_prompt)
                            refund_iteration()
                            continue

                        # 通用可追溯性约束：必须显式输出真实列名/类型证据，避免“编造字段/默认 0”导致结论不可复现。
                        # 不 hardcode 任何业务列名，仅要求代码必须读取 CSV 后引用 df.columns/dtypes。
                        mentions_columns = (
                            "df.columns" in normalized_code
                            or "columns.tolist" in normalized_code
                            or "dtypes" in normalized_code
                        )
                        if not mentions_columns:
                            logger.warning(
                                "[bot_stream] Code rejected: html_report_phase2 missing schema evidence (df.columns/dtypes)"
                            )
                            evidence_prompt = (
                                f"第 {target_round} 轮综合 HTML 报告必须基于 generated/ 下真实 CSV 计算，并在代码中显式输出/写入可追溯证据："
                                "至少包含 `df.columns.tolist()`（真实列名）、`df.dtypes`（真实类型）和 `len(df)`（行数）。"
                                "\n\n注意：\n"
                                "- 只能对 `df.select_dtypes(include='number')` 的列做均值/标准差等数值统计，或使用 `mean(numeric_only=True)`；"
                                "- 若没有可用数值列或某项无法解析，请在报告中输出 `N/A`，不要用 0 作为默认值；"
                                "- 任何洞察/指标都必须能对应到真实列名（来自 df.columns），禁止臆造字段名。"
                            )
                            append_user_prompt(evidence_prompt)
                            refund_iteration()
                            continue

                        # 通用“分析型结论”约束：必须做出可追溯的统计计算，避免只做文件罗列导致报告缺少结论。
                        # 不 hardcode 任何具体列名，只要求用真实列名生成至少若干条洞察（TopK/占比/缺失率/唯一值数/数值摘要等）。
                        has_any_stats = any(
                            kw in normalized_code
                            for kw in [
                                "value_counts",
                                "nunique",
                                "isnull",
                                "notnull",
                                "describe(",
                                "select_dtypes",
                                "mean(",
                                "median(",
                                "quantile",
                            ]
                        )
                        if not has_any_stats:
                            logger.warning(
                                "[bot_stream] Code rejected: html_report_phase2 missing any analysis stats (value_counts/nunique/isnull/describe)"
                            )
                            analysis_prompt = (
                                f"第 {target_round} 轮综合报告必须是**分析型**的：请基于你读取的真实 CSV 计算并写入至少 3 条可追溯洞察（不要泛泛而谈）。"
                                "\n\n要求（通用，不依赖特定列名）：\n"
                                "- 每条洞察必须明确引用真实列名（来自 `df.columns`），并附带你计算出的数值证据；\n"
                                "- 若存在类别列：用 `value_counts().head(k)` 给出 TopK 类别及占比；\n"
                                "- 若存在数值列：对 `df.select_dtypes(include='number')` 做 mean/median/quantile 等摘要；\n"
                                "- 必须给出缺失情况：例如每列缺失数/缺失率（`df.isnull().sum()`）；\n"
                                "- 建议在 HTML 中新增 `<section id='insights'>`，用 `<ul><li>...` 写出这些洞察，并确保所有数字来自代码计算结果；\n"
                                "- 若没有任何数值列，也必须输出基于类别列/缺失率/唯一值数量（`nunique()`）的结论。"
                            )
                            append_user_prompt(analysis_prompt)
                            refund_iteration()
                            continue

                    elif mode_for_next == "csv_analysis":
                        if not uses_csv:
                            logger.warning(
                                f"[bot_stream] Code rejected: round {target_round} missing CSV read"
                            )
                            csv_prompt = (
                                f"第 {target_round} 轮属于 CSV 分析阶段，必须使用 `pd.read_csv` 读取配置中指定的 CSV 绝对路径，"
                                "禁止跳过 CSV 读取或改用 SQLite。"
                            )
                            messages.append({"role": "user", "content": csv_prompt})
                            refund_iteration()
                            continue
                        if uses_sqlite:
                            logger.warning(
                                f"[bot_stream] Code rejected: round {target_round} should not connect SQLite"
                            )
                            sqlite_prompt = (
                                f"第 {target_round} 轮仅允许 CSV 分析，禁止使用 `sqlite3.connect` 或 SQL 查询。"
                                "请删除 SQLite 相关代码，仅通过 pandas 读取 CSV 并输出统计结果。"
                            )
                            messages.append({"role": "user", "content": sqlite_prompt})
                            refund_iteration()
                            continue

                        required_csv = (
                            round_input_filename(rule_for_next)
                            if rule_for_next
                            else None
                        )
                        if required_csv:
                            normalized_code_for_path = effective_code.lower()
                            if required_csv.lower() not in normalized_code_for_path:
                                logger.warning(
                                    "[bot_stream] Round %s CSV mismatch: expected %s",
                                    target_round,
                                    required_csv,
                                )
                                csv_name_prompt = (
                                    f"第 {target_round} 轮必须使用第 1 轮列出的 `{required_csv}`，"
                                    "请直接引用该 CSV 的绝对路径，不要改用其它文件名或虚构的 student_loan_data.csv。"
                                )
                                messages.append(
                                    {"role": "user", "content": csv_name_prompt}
                                )
                                refund_iteration()
                                continue

                    elif mode_for_next == "filesystem_summary":
                        if code_looks_like_markdown(effective_code):
                            logger.warning(
                                "[bot_stream] Code rejected: filesystem summary must write README via Python"
                            )
                            markdown_prompt = (
                                f"第 {target_round} 轮需要输出 Python 脚本，使用 pathlib/os 等遍历 generated/ 并写入 README.md。"
                                " 请不要直接在 <Code> 中粘贴 Markdown，务必通过 `Path('generated/README.md').write_text(...)` 等方式生成文件。"
                            )
                            messages.append(
                                {"role": "user", "content": markdown_prompt}
                            )
                            refund_iteration()
                            continue
                        if not has_filesystem_write_operations(effective_code):
                            logger.warning(
                                "[bot_stream] Code rejected: filesystem summary missing filesystem write"
                            )
                            write_prompt = (
                                f"第 {target_round} 轮必须使用 pathlib/os 写入 README.md（如 Path('generated/README.md').write_text(...)）。"
                                " 当前检测不到任何写盘操作，请参考提示词提供的模板，确保脚本真正生成 README.md 文件。"
                            )
                            messages.append({"role": "user", "content": write_prompt})
                            refund_iteration()
                            continue

                    if mode_for_next == "sqlite_join":
                        if not uses_sqlite:
                            logger.warning(
                                f"[bot_stream] Code rejected: round {target_round} must use SQLite JOIN"
                            )
                            join_prompt = (
                                f"第 {target_round} 轮必须通过 `sqlite3.connect(DB_PATH, timeout=30)` 执行多表 JOIN，"
                                "禁止改用 CSV。请基于配置列出的真实表完成 SQL 查询，再写出结果 CSV/PNG。"
                            )
                            append_user_prompt(join_prompt)
                            refund_iteration()
                            continue

                        if rule_for_next and rule_requires_busy_timeout(rule_for_next):
                            if "pragma busy_timeout" not in normalized_code:
                                logger.warning(
                                    "[bot_stream] Code rejected: round %s missing PRAGMA busy_timeout",
                                    target_round,
                                )
                                busy_prompt = (
                                    f"第 {target_round} 轮必须在连接 SQLite 后执行 "
                                    '`conn.execute("PRAGMA busy_timeout = 30000;")` 以保证查询稳定。'
                                )
                                append_user_prompt(busy_prompt)
                                refund_iteration()
                                continue

                        expected_join_csvs = (
                            round_expected_filenames_by_type(rule_for_next, "csv")
                            if rule_for_next
                            else []
                        )
                        normalized_code_lower = effective_code.lower()

                        expected_sqlite = find_primary_sqlite(Path(workspace_path))
                        if expected_sqlite:
                            expected_sqlite_path = str(expected_sqlite.resolve())
                            references_expected_sqlite = (
                                expected_sqlite_path.lower() in normalized_code_lower
                            )
                            if not references_expected_sqlite:
                                logger.warning(
                                    "[bot_stream] Code rejected: round %s missing expected SQLite path",
                                    target_round,
                                )
                                sqlite_path_prompt = (
                                    "第 {round} 轮必须使用首轮提示中提供的数据库绝对路径：\n"
                                    '```python\nDB_PATH = r"{path}"\n```\n'
                                    "请删除 `education.db` / `data/student_loan.sqlite` 等无关路径，改为以上路径，并重新执行 SQLite JOIN。"
                                ).format(round=target_round, path=expected_sqlite_path)
                                append_user_prompt(sqlite_path_prompt)
                                refund_iteration()
                                continue

                        for csv_name in expected_join_csvs:
                            csv_lower = csv_name.lower()
                            csv_path = generated_dir / csv_name
                            references_join_csv = (
                                csv_lower in normalized_code_lower
                                and "pd.read_csv" in normalized_code_lower
                            )
                            writes_join_csv = (
                                csv_lower in normalized_code_lower
                                and ".to_csv" in normalized_code_lower
                            )
                            if (
                                references_join_csv
                                and not csv_path.exists()
                                and not writes_join_csv
                            ):
                                logger.warning(
                                    "[bot_stream] Code rejected: round %s reading missing %s",
                                    target_round,
                                    csv_name,
                                )
                                warn_join_file = (
                                    f"检测到你尝试 `pd.read_csv('.../{csv_name}')`，但该文件尚未生成。"
                                    f"第 {target_round} 轮必须先通过 SQLite JOIN 生成 `{csv_name}`，再基于结果做分析。"
                                    "请在同一段代码中完成 SQL JOIN 并写入该 CSV。"
                                )
                                append_user_prompt(warn_join_file)
                                refund_iteration()
                                continue

                    if DDL_TABLE_PATTERN.search(normalized_code):
                        logger.warning(
                            f"[bot_stream] Code rejected: DDL operation detected"
                        )
                        ddl_prompt = (
                            "检测到脚本尝试执行 `CREATE/DROP/ALTER TABLE` 等操作。"
                            " 出于数据安全考虑，本系统禁止修改数据库结构，请改为针对已有表进行查询或分析。"
                        )
                        messages.append({"role": "user", "content": ddl_prompt})
                        refund_iteration()
                        continue
                    # 检测是否只查询 sqlite_master 而不查询真实表
                    has_sqlite_master_query = "sqlite_master" in normalized_code
                    has_real_table_query = (
                        any(
                            f"from {tbl}" in normalized_code.lower()
                            or f"from `{tbl}`" in normalized_code.lower()
                            for tbl in known_tables
                        )
                        if known_tables
                        else False
                    )

                    if (
                        schema_confirmed
                        and has_sqlite_master_query
                        and not has_real_table_query
                        and "pragma" not in normalized_code
                        and mode_for_next != "html_report_phase2"
                    ):
                        logger.warning(
                            f"[bot_stream] Code rejected: only sqlite_master query after schema confirmed"
                        )
                        schema_only_repeat += 1
                        table_examples = sorted(known_tables)
                        example_text = (
                            ", ".join(table_examples[:3])
                            if table_examples
                            else "真实表"
                        )
                        sample_next = (
                            f"例如：SELECT * FROM {table_examples[0]} LIMIT 5"
                            if table_examples
                            else "例如：SELECT * FROM 某个真实表 LIMIT 5"
                        )
                        refresh_prompt = (
                            "表结构已经明确，无需再次**单独**查询 sqlite_master。请直接对真实表（如："
                            + example_text
                            + f"）执行 SELECT/EDA，比如 {sample_next} 或绘制对应字段的分布。\n\n"
                            "如果需要动态获取表名列表，可以在代码中查询 sqlite_master 后立即对真实表执行分析。"
                        )
                        if schema_only_repeat >= 3:
                            violation_block = (
                                "\n<Answer>\n已确认表结构后仍连续 3 轮只查询 sqlite_master 而不分析真实表，任务被自动终止。"
                                " 请重新发起会话，并在首轮之外直接针对真实表执行 SELECT/EDA。\n</Answer>\n"
                            )
                            assistant_reply += violation_block
                            yield violation_block
                            return
                        messages.append({"role": "user", "content": refresh_prompt})
                        refund_iteration()
                        continue
                    else:
                        schema_only_repeat = 0

                    # 在使用 mode_for_current 之前提前解析当前轮配置，避免未定义访问
                    rule_for_current = get_round_rule(current_round)
                    mode_for_current = round_mode(rule_for_current)

                    sql_tables_used: set[str] = set()
                    if mode_for_current == "filesystem_summary":
                        if uses_sqlite:
                            logger.warning(
                                "[bot_stream] Code rejected: filesystem summary round should not execute SQL"
                            )
                            readme_sql_prompt = (
                                "第 8 轮任务仅需遍历 generated/ 目录生成 README.md，禁止连接 SQLite 或执行 SQL。"
                                " 请删除 SQL 片段，仅使用 pathlib/os/json 等遍历文件系统并写入 Markdown。"
                            )
                            messages.append(
                                {"role": "user", "content": readme_sql_prompt}
                            )
                            refund_iteration()
                            continue
                    else:
                        if uses_sqlite:
                            sql_tables_used = extract_sql_table_names(effective_code)
                            if sql_tables_used:
                                recent_tables_used = sql_tables_used
                    invalid_tables = set()
                    if known_tables and sql_tables_used:
                        invalid_tables = {
                            tbl
                            for tbl in sql_tables_used
                            if tbl not in known_tables
                            and tbl.lower() not in {"sqlite_master", "sqlite_sequence"}
                            and tbl.lower() not in COMMON_WORDS_GLOBAL
                        }

                    invalid_lower = {tbl.lower() for tbl in invalid_tables}
                    forbidden_refs = invalid_lower & PROHIBITED_TABLES
                    if forbidden_refs:
                        forbidden_prompt = (
                            "检测到脚本尝试访问系统保留/不存在的表："
                            + ", ".join(sorted(forbidden_refs))
                            + "。请改用 sqlite_master 中真实存在的表（例如："
                            + ", ".join(sorted(list(known_tables)[:3]))  # may be empty
                            + "）。"
                        )
                        if not known_tables:
                            forbidden_prompt = forbidden_prompt.replace(
                                "（例如：）",
                                "（请参考首轮 sqlite_master 返回的实际表名）",
                            )
                        messages.append({"role": "user", "content": forbidden_prompt})
                        refund_iteration()
                        continue

                    if schema_confirmed and invalid_tables:
                        logger.warning(
                            f"[bot_stream] Code rejected: invalid tables {invalid_tables}"
                        )
                        valid_tables_list = (
                            ", ".join(sorted(known_tables)) if known_tables else "无"
                        )
                        invalid_msg = (
                            f"❌ 脚本中引用了不存在的表：{', '.join(sorted(invalid_tables))}\n\n"
                            f"✅ 数据库中真实存在的表（来自首轮 sqlite_master 查询）：\n{valid_tables_list}\n\n"
                            "⚠️ 请严格使用上述真实表名，不要使用任何虚构的表名（如 Integrity、Validity、Frequency 等）。\n"
                            "所有表均只有 name 列作为关联键，其余字段请参考首轮输出的表结构。"
                        )
                        messages.append({"role": "user", "content": invalid_msg})
                        refund_iteration()
                        continue

                    post_execute_prompts: list[str] = []

                    if not schema_confirmed and "sqlite_master" not in normalized_code:
                        logger.warning(
                            f"[bot_stream] Code rejected: schema not confirmed and no sqlite_master query (schema_confirmed={schema_confirmed})"
                        )
                        schema_prompt = (
                            "请先在 <Code> 中执行 `SELECT name FROM sqlite_master WHERE type='table'` 并列出真实表结构，"
                            "首轮必须完成表结构确认后才能继续 EDA。"
                        )
                        messages.append({"role": "user", "content": schema_prompt})
                        refund_iteration()
                        continue

                    missing_imports = []
                    if (
                        "pd." in effective_code
                        and "import pandas as pd" not in effective_code
                    ):
                        missing_imports.append("import pandas as pd")
                    if (
                        "plt." in effective_code
                        and "import matplotlib.pyplot as plt" not in effective_code
                    ):
                        missing_imports.append("import matplotlib.pyplot as plt")
                    if (
                        "sns." in effective_code
                        and "import seaborn as sns" not in effective_code
                    ):
                        missing_imports.append("import seaborn as sns")

                    uses_np = "np." in effective_code
                    has_np_import = "import numpy as np" in effective_code
                    if uses_np and not has_np_import:
                        # 第三方导入缺失可自愈：避免因为 np 未导入导致 NameError 触发反复重试
                        lines = effective_code.splitlines()
                        insert_at = 0
                        for i, line in enumerate(lines):
                            stripped = line.strip()
                            if not stripped:
                                continue
                            if stripped.startswith("import ") or stripped.startswith(
                                "from "
                            ):
                                insert_at = i + 1
                                continue
                            break
                        lines.insert(insert_at, "import numpy as np")
                        effective_code = "\n".join(lines)
                    uses_path = (
                        "Path(" in effective_code or "pathlib.Path" in effective_code
                    )
                    has_path_import = (
                        "from pathlib import Path" in effective_code
                        or "import pathlib" in effective_code
                    )
                    if uses_path and not has_path_import:
                        # 标准库导入缺失可自愈：避免模型因小错误被拒绝后再输出无 <Code> 导致卡死
                        lines = effective_code.splitlines()
                        insert_at = 0
                        for i, line in enumerate(lines):
                            stripped = line.strip()
                            if not stripped:
                                continue
                            if stripped.startswith("import ") or stripped.startswith(
                                "from "
                            ):
                                insert_at = i + 1
                                continue
                            break
                        lines.insert(insert_at, "from pathlib import Path")
                        effective_code = "\n".join(lines)
                        has_path_import = True
                    if missing_imports:
                        logger.warning(
                            f"[bot_stream] Code rejected: missing imports {missing_imports}"
                        )
                        import_prompt = (
                            "检测到 <Code> 使用了 pandas/matplotlib/seaborn，但缺少以下导入："
                            + ", ".join(missing_imports)
                            + "。请补全导入后再执行。"
                        )
                        messages.append({"role": "user", "content": import_prompt})
                        refund_iteration()
                        continue

                    # 检测是否使用了 DB_PATH 或 OUTPUT_DIR 但未定义
                    uses_db_path = "DB_PATH" in effective_code
                    uses_output_dir = "OUTPUT_DIR" in effective_code
                    defines_db_path = (
                        "DB_PATH = " in effective_code or "DB_PATH=" in effective_code
                    )
                    defines_output_dir = (
                        "OUTPUT_DIR = " in effective_code
                        or "OUTPUT_DIR=" in effective_code
                    )

                    if uses_db_path and not defines_db_path:
                        logger.warning(
                            f"[bot_stream] Code rejected: uses DB_PATH but not defined"
                        )
                        available_sqlite_files = iter_sqlite_files(workspace_path)
                        sample_display = ""
                        if available_sqlite_files:
                            sample = available_sqlite_files[0]
                            sample_display = str(sample.resolve())

                        db_path_prompt = "❌ 错误：代码中使用了 `DB_PATH` 变量，但未在代码开头定义。\n\n"
                        if sample_display:
                            db_path_prompt += (
                                f"✅ **必须在代码开头定义**：\n"
                                f"```python\nDB_PATH = r'{sample_display}'\n```\n\n"
                                "请在所有 import 语句之后、使用 DB_PATH 之前添加上述定义。"
                            )
                        else:
                            db_path_prompt += "请在代码开头定义 DB_PATH 变量，指向 workspace 中实际存在的 sqlite 文件的绝对路径。"
                        messages.append({"role": "user", "content": db_path_prompt})
                        refund_iteration()
                        continue

                    if uses_output_dir and not defines_output_dir:
                        logger.warning(
                            f"[bot_stream] Code rejected: uses OUTPUT_DIR but not defined"
                        )
                        output_dir_prompt = (
                            "❌ 错误：代码中使用了 `OUTPUT_DIR` 变量，但未在代码开头定义。\n\n"
                            "✅ **必须在代码开头定义**：\n"
                            "```python\n"
                            "from pathlib import Path\n"
                            "OUTPUT_DIR = Path('generated')\n"
                            "OUTPUT_DIR.mkdir(parents=True, exist_ok=True)\n"
                            "```\n\n"
                            "请在所有 import 语句之后、使用 OUTPUT_DIR 之前添加上述定义。"
                        )
                        messages.append({"role": "user", "content": output_dir_prompt})
                        refund_iteration()
                        continue

                    # 移除强制要求sqlite3.connect的检查
                    # CSV读取代码不需要sqlite3连接,只有SQLite操作才需要
                    # 该检查已被上面的智能检查替代

                    connect_paths = SQLITE_CONNECT_PATTERN.findall(effective_code)
                    if connect_paths:
                        available_sqlite_files = iter_sqlite_files(workspace_path)
                        available_resolved = {
                            p.resolve(): p for p in available_sqlite_files
                        }
                        invalid_connects: list[str] = []
                        for raw_path in connect_paths:
                            # 强制拒绝相对路径
                            if not Path(raw_path).is_absolute():
                                invalid_connects.append(raw_path)
                                continue
                            try:
                                candidate = Path(raw_path).resolve()
                            except Exception:
                                candidate = Path(raw_path)
                            if candidate.resolve() not in available_resolved:
                                invalid_connects.append(raw_path)
                        if invalid_connects:
                            logger.warning(
                                f"[bot_stream] Code rejected: invalid database path(s): {invalid_connects}"
                            )
                            sample_display = ""
                            if available_sqlite_files:
                                sample = available_sqlite_files[0]
                                # 使用绝对路径，确保代码执行时能找到文件
                                sample_display = str(sample.resolve())
                            path_prompt = (
                                "❌ 错误：检测到 `sqlite3.connect` 使用了相对路径或不存在的文件："
                                + ", ".join(f"`{p}`" for p in invalid_connects)
                                + "。\n\n"
                            )
                            if sample_display:
                                path_prompt += (
                                    f"✅ **必须使用绝对路径**：`DB_PATH = r'{sample_display}'`\n\n"
                                    "请将代码中的 `sqlite3.connect(...)` 改为：\n"
                                    f"```python\nDB_PATH = r'{sample_display}'\n"
                                    "with sqlite3.connect(DB_PATH, timeout=30) as conn:\n"
                                    '    conn.execute("PRAGMA busy_timeout = 30000;")\n'
                                    "    # 你的查询代码\n"
                                    "```\n"
                                    "**禁止使用相对路径**，否则代码执行时无法找到数据库文件。"
                                )
                            else:
                                path_prompt += "请使用 workspace 中实际存在的 sqlite 文件的绝对路径。"
                            messages.append({"role": "user", "content": path_prompt})
                            refund_iteration()
                            continue

                    uses_plot = "plt." in normalized_code or "sns." in normalized_code
                    requires_png = (
                        rule_for_next is not None
                        and round_requires_output_type(rule_for_next, "png")
                    )
                    if (
                        uses_plot
                        and requires_png
                        and "plt.savefig" not in normalized_code
                    ):
                        logger.warning(
                            f"[bot_stream] Code rejected: missing plt.savefig"
                        )
                        save_prompt = (
                            "绘图脚本必须调用 `plt.savefig('generated/xxx.png')` 并写入实际文件，再在 <File> 中引用。"
                            " 请补充 `plt.savefig` 后重新提交。"
                        )
                        messages.append({"role": "user", "content": save_prompt})
                        refund_iteration()
                        continue
                    if (
                        uses_plot
                        and requires_png
                        and "plt.close" not in normalized_code
                    ):
                        close_prompt = "绘图结束后需调用 `plt.close()` 释放资源，避免多轮叠加。请在 <Code> 末尾补充 `plt.close()`。"
                        messages.append({"role": "user", "content": close_prompt})
                        refund_iteration()
                        continue

                    target_round = execute_rounds + 1
                    if target_round == 7:
                        uses_sqlite_join = any(
                            key in normalized_code
                            for key in [
                                "sqlite3.connect",
                                "pd.read_sql(",
                                "pd.read_sql_query",
                                "pd.read_sql_table",
                            ]
                        )
                        if not uses_sqlite_join:
                            logger.warning(
                                "[bot_stream] Code rejected: round 7 must use SQLite join"
                            )
                            join_prompt = (
                                "第 7 轮必须使用 SQLite 多表 JOIN：\n"
                                "1. 在 <Code> 开头通过 `sqlite3.connect(DB_PATH, timeout=30)` 建立连接\n"
                                "2. 基于 `enrolled/no_payment_due/longest_absense_from_school/enlist/disabled` 等真实表执行 JOIN 查询\n"
                                "3. 将 JOIN 结果写入 `generated/multi_table_join_result.csv`\n"
                                "4. 再对合并结果做统计与绘图\n\n"
                                "请使用 SQLite 查询而不是直接使用 CSV/multi_table_join_result.csv。"
                            )
                            messages.append({"role": "user", "content": join_prompt})
                            refund_iteration()
                            continue

                        join_csv_path = generated_dir / "multi_table_join_result.csv"
                        references_join_csv = (
                            "multi_table_join_result" in normalized_code
                            and "pd.read_csv" in normalized_code
                        )
                        writes_join_csv = (
                            "multi_table_join_result" in normalized_code
                            and ".to_csv" in normalized_code
                        )
                        if (
                            references_join_csv
                            and not join_csv_path.exists()
                            and not writes_join_csv
                        ):
                            logger.warning(
                                "[bot_stream] Code rejected: round 7 reading missing multi_table_join_result.csv"
                            )
                            warn_join_file = (
                                "检测到你尝试 `pd.read_csv('.../multi_table_join_result.csv')`，"
                                "但该文件尚未生成。第 7 轮必须先通过 SQLite JOIN 生成该 CSV，"
                                "再基于结果做分析。请在同一段代码中完成 SQL JOIN 并写入 `generated/multi_table_join_result.csv`。"
                            )
                            messages.append({"role": "user", "content": warn_join_file})
                            refund_iteration()
                            continue

                        if "pragma busy_timeout" not in normalized_code:
                            logger.warning(
                                "[bot_stream] Code rejected: round 7 missing PRAGMA busy_timeout"
                            )
                            busy_prompt = (
                                "第 7 轮必须在连接 SQLite 后执行 "
                                '`conn.execute("PRAGMA busy_timeout = 30000;")` 以保证查询稳定。'
                                "请补充该语句后重新提交。"
                            )
                            messages.append({"role": "user", "content": busy_prompt})
                            refund_iteration()
                            continue

                    # 强制检查：第2轮起必须包含文件写入操作（根据 round_io_rules 配置）
                    if non_schema_exec_rounds > 0:
                        if mode_for_next == "filesystem_summary":
                            logger.info(
                                "[bot_stream] File output check skipped for filesystem summary round"
                            )
                        else:
                            expected_types = (
                                round_expected_types(rule_for_next)
                                if rule_for_next
                                else set()
                            )
                            needs_csv = "csv" in expected_types
                            needs_png = "png" in expected_types
                            has_csv_output = ".to_csv(" in normalized_code
                            has_png_output = (
                                "plt.savefig(" in normalized_code
                                or ".savefig(" in normalized_code
                            )
                            missing_requirements: list[str] = []
                            if needs_csv and not has_csv_output:
                                missing_requirements.append("CSV 文件输出（.to_csv）")
                            if needs_png and not has_png_output:
                                missing_requirements.append(
                                    "PNG 图像输出（plt.savefig）"
                                )
                            if missing_requirements:
                                logger.warning(
                                    "[bot_stream] Code rejected: round %s missing outputs %s",
                                    target_round,
                                    ", ".join(missing_requirements),
                                )
                                file_output_prompt = (
                                    f"根据 round_io_rules 配置，第 {target_round} 轮需要生成："
                                    + "、".join(missing_requirements)
                                    + "。请在 <Code> 中补充相应的写盘语句后重新提交。"
                                )
                                messages.append(
                                    {"role": "user", "content": file_output_prompt}
                                )
                                refund_iteration()
                                continue
                            if not expected_types and not (
                                has_csv_output or has_png_output
                            ):
                                logger.warning(
                                    f"[bot_stream] Code rejected: missing file output (CSV/PNG)"
                                )
                                file_output_prompt = (
                                    "第 2 轮起每个 <Code> 必须生成至少一个 CSV 或 PNG 文件。"
                                    " 请添加 `DataFrame.to_csv(...)` 或 `plt.savefig(...)` 并写入 generated/。"
                                )
                                messages.append(
                                    {"role": "user", "content": file_output_prompt}
                                )
                                refund_iteration()
                                continue

                    last_code_signature = code_signature

                    if (
                        mode_for_next == "filesystem_summary"
                        and rule_for_next
                        and "README.md"
                        in round_expected_filenames_by_type(rule_for_next, "markdown")
                    ):
                        try:
                            readme_placeholder = generated_dir / "README.md"
                            readme_placeholder.touch(exist_ok=True)
                        except Exception as err:
                            logger.warning(
                                "[bot_stream] Failed to touch README.md before filesystem summary: %s",
                                err,
                            )

                    logger.info(
                        f"[bot_stream] session={session_id} iteration={iteration} executing code, length={len(code_str)}"
                    )
                    logger.info(
                        f"[bot_stream] Code preview: {(effective_code or code_str)[:200]}..."
                    )
                    try:
                        before_state = {
                            p.resolve(): (p.stat().st_size, p.stat().st_mtime_ns)
                            for p in workspace_path.rglob("*")
                            if p.is_file()
                        }
                    except Exception:
                        before_state = {}

                    exe_output = execute_code_safe(
                        effective_code or code_str, str(workspace_path)
                    )
                    code_executed = True

                    # 将执行输出写入日志文件
                    try:
                        log_file = (
                            generated_dir / f"execute_round_{execute_rounds + 1}.txt"
                        )
                        with open(log_file, "w", encoding="utf-8") as f:
                            f.write(f"=== Execution Round {execute_rounds + 1} ===\n")
                            f.write(f"Session: {session_id}\n")
                            f.write(f"Iteration: {iteration}\n\n")
                            f.write("=== Code ===\n")
                            f.write(effective_code or code_str)
                            f.write("\n\n=== Output ===\n")
                            f.write(exe_output)
                        logger.info(f"[bot_stream] Wrote execution log to {log_file}")
                    except Exception as log_err:
                        logger.warning(
                            f"[Warning] Failed to write execution log: {log_err}"
                        )

                    is_schema_code = (
                        "sqlite_master" in normalized_code
                        and "pragma" not in normalized_code
                    )

                    if not schema_confirmed and "sqlite_master" in normalized_code:
                        schema_confirmed = True
                        latest_tables = list_sqlite_tables(workspace_path)
                        ensure_known_tables(latest_tables)
                        if not schema_summary_injected:
                            schema_hint = summarize_sqlite_schema(workspace_path)
                            if schema_hint:
                                schema_summary = (
                                    "系统已从实际 sqlite_master/PRAGMA 中解析到以下表结构，请在后续 <Analyze>/<Code> 中"
                                    " 直接引用这些真实名字，并按其中字段推进分析：\n"
                                    f"{schema_hint}\n"
                                    "下一步建议：从上述表中任选一个（如第一张表）执行 `SELECT * ... LIMIT 50` 做初步概览。"
                                )
                                messages.append(
                                    {"role": "user", "content": schema_summary}
                                )
                            schema_summary_injected = True

                    try:
                        after_state = {
                            p.resolve(): (p.stat().st_size, p.stat().st_mtime_ns)
                            for p in workspace_path.rglob("*")
                            if p.is_file()
                        }
                    except Exception:
                        after_state = {}

                    added_paths = [
                        p for p in after_state.keys() if p not in before_state
                    ]
                    modified_paths = [
                        p
                        for p in after_state.keys()
                        if p in before_state and after_state[p] != before_state[p]
                    ]

                    artifact_paths = []
                    generated_dir_path = generated_dir.resolve()
                    generated_dir_str = str(generated_dir_path)
                    rule_for_current = get_round_rule(current_round)
                    expected_files = (
                        round_expected_filenames(rule_for_current)
                        if rule_for_current
                        else []
                    )
                    expected_files_lower = {name.lower() for name in expected_files}

                    def is_in_generated(path_obj: Path) -> bool:
                        try:
                            return str(path_obj.resolve()).startswith(generated_dir_str)
                        except Exception:
                            return False

                    logger.info(
                        f"[bot_stream] Added files: {[str(p) for p in added_paths]}"
                    )
                    logger.info(
                        f"[bot_stream] Modified files: {[str(p) for p in modified_paths]}"
                    )
                    for p in added_paths:
                        try:
                            resolved = p.resolve()
                            # 如果文件已经在 generated 目录下,直接使用,不要创建副本
                            if is_in_generated(resolved):
                                logger.info(
                                    f"[bot_stream] File already in generated: {resolved}"
                                )
                                artifact_paths.append(resolved)
                            else:
                                # 文件在其他位置,需要复制到 generated 目录
                                target_path = generated_dir_path / resolved.name
                                dest_path = uniquify_path(target_path)
                                logger.info(
                                    f"[bot_stream] Copying {resolved} -> {dest_path}"
                                )
                                shutil.copy2(resolved, dest_path)
                                artifact_paths.append(dest_path.resolve())
                        except Exception as e:
                            logger.error(f"[bot_stream] Error processing file {p}: {e}")

                    for p in modified_paths:
                        try:
                            resolved = p.resolve()
                            if is_in_generated(resolved):
                                # 已在 generated 中的文件(如 execute_round_x.txt)直接纳入,避免生成 _modified 副本
                                logger.info(
                                    f"[bot_stream] Modified file already in generated: {resolved}"
                                )
                                if resolved not in artifact_paths:
                                    artifact_paths.append(resolved)
                                continue
                            if (
                                resolved.name.lower() == "readme.md"
                                and "readme.md" in expected_files_lower
                            ):
                                target_path = generated_dir_path / "README.md"
                                logger.info(
                                    "[bot_stream] Copying README.md to generated: %s -> %s",
                                    resolved,
                                    target_path,
                                )
                                shutil.copy2(resolved, target_path)
                                artifact_paths.append(target_path.resolve())
                                continue
                            if resolved.name.lower() in expected_files_lower:
                                target_path = generated_dir_path / resolved.name
                                logger.info(
                                    "[bot_stream] Copying expected artifact to generated: %s -> %s",
                                    resolved,
                                    target_path,
                                )
                                shutil.copy2(resolved, target_path)
                                artifact_paths.append(target_path.resolve())
                                continue
                            dest_path = uniquify_path(
                                generated_dir_path
                                / f"{resolved.stem}_modified{resolved.suffix}"
                            )
                            shutil.copy2(resolved, dest_path)
                            artifact_paths.append(dest_path.resolve())
                        except Exception as e:
                            logger.error(f"Error copying modified file {p}: {e}")

                    mode_for_current = round_mode(rule_for_current)
                    if rule_for_current:
                        produced_names = {Path(p).name for p in artifact_paths}
                        # 重要：不能只用本轮 artifact_paths 判断“是否生成”。
                        # 例如 README.md 可能在 generated/ 内被覆盖写入，但未被 modified_paths 捕获。
                        # 因此这里也认可 generated/ 目录里已存在的期望文件。
                        missing_files = [
                            name
                            for name in expected_files
                            if name not in produced_names
                            and not (generated_dir_path / name).exists()
                        ]
                        if missing_files:
                            logger.warning(
                                "[bot_stream] Round %s outputs missing required filenames: %s",
                                current_round,
                                ", ".join(missing_files),
                            )
                            produced_hint = "，本轮检测到的文件：" + (
                                ", ".join(sorted(produced_names))
                                if produced_names
                                else "无"
                            )
                            required_list = ", ".join(expected_files)
                            missing_list = ", ".join(missing_files)
                            unexpected_md_files = sorted(
                                {
                                    name
                                    for name in produced_names
                                    if name.lower().endswith(".md")
                                    and name.lower() not in expected_files_lower
                                }
                            )
                            extra_md_hint = ""
                            if unexpected_md_files:
                                extra_md_hint = (
                                    "另外检测到未在本轮 outputs 中声明的 Markdown 文件："
                                    + ", ".join(unexpected_md_files)
                                    + "。请删除这些 .md 文件，严格按要求生成 HTML 文件。"
                                )
                            prompt = (
                                f"根据 round_io_rules 配置，第 {current_round} 轮必须生成："
                                f"{required_list}。当前缺少：{missing_list}"
                                + produced_hint
                                + "。请在本轮同时生成所有要求文件（包含已生成的），不要遗漏任何必需产物。"
                                + extra_md_hint
                            )
                            append_user_prompt(prompt)
                            # 缺少必需产物时，允许模型在下一次重试中保持相同的总体结构，但必须补齐缺失文件。
                            # 若不重置签名，模型可能因为“duplicate code”被拒绝，从而漂移输出无关代码导致死循环。
                            last_code_signature = None
                            refund_iteration()
                            continue

                    if rule_for_current and mode_for_current in (
                        "html_report",
                        "html_report_phase2",
                    ):
                        unexpected_md_files = sorted(
                            {
                                Path(p).name
                                for p in artifact_paths
                                if Path(p).suffix.lower() == ".md"
                                and Path(p).name.lower() not in expected_files_lower
                            }
                        )
                        if unexpected_md_files:
                            logger.warning(
                                "[bot_stream] Round %s produced unexpected markdown files: %s",
                                current_round,
                                ", ".join(unexpected_md_files),
                            )
                            expected_list = (
                                ", ".join(expected_files)
                                if expected_files
                                else "（无）"
                            )
                            prompt = (
                                f"第 {current_round} 轮属于 HTML 报告阶段（{mode_for_current}），"
                                f"根据 round_io_rules 本轮只允许生成：{expected_list}。"
                                f"检测到多余的 Markdown 文件：{', '.join(unexpected_md_files)}。"
                                "请删除这些 .md 文件，并改为生成规则要求的 HTML 文件："
                                "必须使用 Python 构造 html_lines 列表并写入 generated/ 目录，"
                                "禁止生成 Markdown 报告替代 HTML。"
                            )
                            append_user_prompt(prompt)
                            refund_iteration()
                            continue
                    if (
                        mode_for_current == "filesystem_summary"
                        and "readme.md" in expected_files_lower
                    ):
                        extra_md_files = sorted(
                            {
                                Path(p).name
                                for p in artifact_paths
                                if Path(p).suffix.lower() == ".md"
                                and Path(p).name.lower() not in expected_files_lower
                            }
                        )
                        if extra_md_files:
                            logger.warning(
                                "[bot_stream] Round %s produced unexpected markdown files: %s",
                                current_round,
                                ", ".join(extra_md_files),
                            )
                            extra_prompt = (
                                f"第 {current_round} 轮仅允许生成 README.md。"
                                f"检测到多余的 Markdown 文件：{', '.join(extra_md_files)}。"
                                "请删除这些文件并仅生成 README.md。"
                            )
                            messages.append({"role": "user", "content": extra_prompt})
                            refund_iteration()
                            continue

                    disallowed_field_type_files = [
                        Path(p)
                        for p in artifact_paths
                        if Path(p).name.lower().endswith("_field_types.txt")
                    ]
                    if disallowed_field_type_files:
                        logger.warning(
                            "[bot_stream] Detected disallowed *_field_types.txt files: %s",
                            ", ".join(str(p.name) for p in disallowed_field_type_files),
                        )
                        prompt = (
                            "请不要在任何轮次额外生成 `*_field_types.txt` 这类辅助文件。"
                            "本轮仅允许输出 round_io_rules 中指定的 CSV/PNG/README/HTML 产物。"
                            "请删除这些多余文件后重新提交。"
                        )
                        messages.append({"role": "user", "content": prompt})
                        refund_iteration()
                        continue

                    if (
                        mode_for_current == "filesystem_summary"
                        and rule_for_current
                        and "README.md"
                        in round_expected_filenames_by_type(
                            rule_for_current, "markdown"
                        )
                    ):
                        readme_path = next(
                            (
                                Path(p)
                                for p in artifact_paths
                                if Path(p).name.lower() == "readme.md"
                            ),
                            None,
                        )
                        if readme_path:
                            try:
                                readme_text = readme_path.read_text(encoding="utf-8")
                            except Exception as err:
                                logger.warning(
                                    f"[bot_stream] Failed to read README.md for validation: {err}"
                                )
                                readme_text = ""
                            is_valid_readme, readme_issues = validate_readme_document(
                                readme_text, generated_dir
                            )
                            if not is_valid_readme:
                                logger.warning(
                                    "[bot_stream] README.md format validation failed in round %s: %s",
                                    current_round,
                                    "; ".join(readme_issues),
                                )
                                detail_prompt = (
                                    "生成的 README.md 未符合规范：\n- "
                                    + "\n- ".join(readme_issues)
                                    + "\n请按照模板遍历 generated/ 目录并重新写入 README.md。"
                                )
                                messages.append(
                                    {"role": "user", "content": detail_prompt}
                                )
                                # 允许下一轮重复 Analyze（因为是同一任务的纠错重试）
                                allow_duplicate_analyze_retry()
                                refund_iteration()
                                continue

                    if (
                        mode_for_current == "html_report"
                        and rule_for_current
                        and round_expected_filenames_by_type(rule_for_current, "html")
                    ):
                        html_filename = round_expected_filenames_by_type(
                            rule_for_current, "html"
                        )[0]
                        html_path = next(
                            (
                                Path(p)
                                for p in artifact_paths
                                if Path(p).name == html_filename
                            ),
                            None,
                        )
                        if html_path:
                            try:
                                html_text = html_path.read_text(encoding="utf-8")
                            except Exception as err:
                                logger.warning(
                                    "[bot_stream] Failed to read %s: %s",
                                    html_filename,
                                    err,
                                )
                                html_text = ""
                            valid_html, html_missing = (
                                html_report_has_required_structure(html_text)
                            )
                            if not valid_html:
                                logger.warning(
                                    "[bot_stream] HTML report validation failed: %s",
                                    ", ".join(html_missing),
                                )
                                prompt = (
                                    f"{html_filename} 结构不符合要求："
                                    + "；".join(html_missing)
                                    + "。请按照提示模板补全 <html>/<head>/<body> 以及 summary/visual/data/readme 四个 section，"
                                    "并重新生成 HTML。"
                                )
                                messages.append({"role": "user", "content": prompt})
                                refund_iteration()
                                continue

                            if html_report_has_placeholders(html_text):
                                logger.warning(
                                    "[bot_stream] HTML report contains unresolved placeholders"
                                )
                                prompt = (
                                    "检测到 HTML 报告中存在未替换的占位符（例如 {rows}/{cols}）。"
                                    "这通常意味着你把模板直接粘贴进了 html_lines，未用真实数据渲染。"
                                    "请确保所有行数/列数/统计值均由 Python 计算后写入 HTML，再重新生成。"
                                )
                                messages.append({"role": "user", "content": prompt})
                                refund_iteration()
                                continue

                            if html_report_has_unfriendly_numpy_repr(html_text):
                                logger.warning(
                                    "[bot_stream] HTML report contains numpy scalar repr"
                                )
                                prompt = (
                                    "检测到 HTML 报告中出现 np.int64/np.float64/numpy.* 等不可读对象表示。"
                                    "请在写入 HTML 前把 pandas/numpy 标量转换为普通 Python 数值（例如 val.item() 或 int(val)/float(val)），"
                                    "避免报告不可读且两次运行表现不一致。"
                                )
                                messages.append({"role": "user", "content": prompt})
                                refund_iteration()
                                continue

                            join_path = generated_dir / "multi_table_join_result.csv"
                            if join_path.exists():
                                try:
                                    join_df = pd.read_csv(join_path)
                                    join_cols = [
                                        str(c) for c in join_df.columns.tolist()
                                    ]
                                except Exception as err:
                                    logger.warning(
                                        "[bot_stream] Failed to read join CSV for HTML validation: %s",
                                        err,
                                    )
                                    join_cols = []

                                if (
                                    join_cols
                                    and not html_report_references_any_columns(
                                        html_text, join_cols
                                    )
                                ):
                                    logger.warning(
                                        "[bot_stream] HTML report missing any join column references"
                                    )
                                    prompt = (
                                        "multi_table_analysis.html 需要包含基于 join 主数据（multi_table_join_result.csv）的分析型结论，"
                                        "但当前 HTML 未引用任何真实列名。请先读取 join CSV，"
                                        "并在‘数据洞察/关键发现’中引用 df.columns 的真实列名与计算出的数值证据（至少 3 条）。"
                                    )
                                    messages.append({"role": "user", "content": prompt})
                                    refund_iteration()
                                    continue

                            li_count = html_text.lower().count("<li")
                            if li_count < 3:
                                logger.warning(
                                    "[bot_stream] HTML report contains too few <li> items: %s",
                                    li_count,
                                )
                                prompt = (
                                    "multi_table_analysis.html 缺少足够的分析型要点。"
                                    "请在报告中加入至少 3 条可追溯的要点（<li>）：每条需引用真实列名并给出计算出的数值依据。"
                                )
                                messages.append({"role": "user", "content": prompt})
                                refund_iteration()
                                continue

                            generated_files = [
                                f
                                for f in generated_dir.iterdir()
                                if f.is_file()
                                and f.name.lower()
                                not in {html_filename.lower(), "readme.md"}
                            ]
                            csv_missing_refs = [
                                f.name
                                for f in generated_files
                                if f.suffix.lower() == ".csv"
                                and f.name not in html_text
                            ]
                            png_missing_refs = [
                                f.name
                                for f in generated_files
                                if f.suffix.lower() == ".png"
                                and f.name not in html_text
                            ]
                            readme_missing = (
                                generated_dir / "README.md"
                            ).exists() and "README.md" not in html_text
                            if csv_missing_refs or png_missing_refs or readme_missing:
                                logger.warning(
                                    "[bot_stream] HTML report missing file references: csv=%s, png=%s, readme_missing=%s",
                                    csv_missing_refs,
                                    png_missing_refs,
                                    readme_missing,
                                )
                                missing_msgs = []
                                if csv_missing_refs:
                                    missing_msgs.append(
                                        "CSV：" + ", ".join(sorted(csv_missing_refs))
                                    )
                                if png_missing_refs:
                                    missing_msgs.append(
                                        "PNG：" + ", ".join(sorted(png_missing_refs))
                                    )
                                if readme_missing:
                                    missing_msgs.append("README.md")
                                prompt = (
                                    "multi_table_analysis.html 需完整列出 generated/ 下的 CSV/PNG/README，"
                                    "但当前缺少："
                                    + "；".join(missing_msgs)
                                    + "。请遍历目录并将文件名写入 HTML 列表后重新生成。"
                                )
                                messages.append({"role": "user", "content": prompt})
                                refund_iteration()
                                continue

                        # Round 9 HTML 生成成功后，更新 README.md 包含 HTML 文件
                        if mode_for_current == "html_report":
                            try:
                                from backend_helpers import update_readme_after_html

                                update_readme_after_html(generated_dir)
                                logger.info(
                                    "[bot_stream] README.md updated with HTML file"
                                )
                            except Exception as err:
                                logger.warning(
                                    "[bot_stream] Failed to update README: %s", err
                                )

                    if current_round == 6:
                        disabled_csv_path = next(
                            (
                                Path(p)
                                for p in artifact_paths
                                if Path(p).name == "disabled_count.csv"
                            ),
                            None,
                        )
                        if disabled_csv_path:
                            try:
                                csv_text = disabled_csv_path.read_text(encoding="utf-8")
                            except Exception as err:
                                logger.warning(
                                    "[bot_stream] Failed to read disabled_count.csv: %s",
                                    err,
                                )
                                csv_text = ""
                            lower_csv_text = csv_text.lower()
                            if (
                                "disabled" not in lower_csv_text
                                or "total" not in lower_csv_text
                            ):
                                logger.warning(
                                    "[bot_stream] disabled_count.csv missing Disabled/Total rows"
                                )
                                prompt = (
                                    "disabled_count.csv 必须同时记录残疾学生数量与总人数，并在 CSV 中出现"
                                    " 'Disabled' 与 'Total'（或相应中文描述）。请重新计算总人数并更新 CSV/PNG。"
                                )
                                messages.append({"role": "user", "content": prompt})
                                refund_iteration()
                                continue

                    exe_str = f"\n<Execute>\n```\n{exe_output}\n```\n</Execute>\n"
                    actual_files = {
                        normalize_filename(Path(p).name) for p in artifact_paths
                    }
                    file_block_lines = ["<File>"]
                    if artifact_paths:
                        for p in artifact_paths:
                            rel = workspace_relative_path(Path(p))
                            url = build_download_url(rel)
                            name = Path(p).name
                            logger.info(
                                f"[bot_stream] File URL: path={p}, rel={rel}, url={url}"
                            )
                            file_block_lines.append(f"- [{name}]({url})")
                            if p.suffix.lower() in [
                                ".png",
                                ".jpg",
                                ".jpeg",
                                ".gif",
                                ".webp",
                                ".svg",
                            ]:
                                file_block_lines.append(f"![{name}]({url})")
                    else:
                        file_block_lines.append("暂无文件")
                    file_block_lines.append("</File>")
                    file_block = "\n" + "\n".join(file_block_lines) + "\n"

                    full_execution_block = exe_str + file_block
                    assistant_reply += full_execution_block
                    yield full_execution_block
                    messages.append({"role": "execute", "content": f"{exe_output}"})
                    if claimed_files_in_round:
                        unmatched_claims = sorted(
                            claim
                            for claim in claimed_files_in_round
                            if claim not in actual_files
                        )
                        if unmatched_claims:
                            warn_block = emit_file_claim_warning(
                                "执行后未发现这些文件产物"
                            )
                            if warn_block:
                                assistant_reply += warn_block
                                yield warn_block
                            warn_missing_file = (
                                "系统未检测到你在 <File> 中声明的文件："
                                + ", ".join(unmatched_claims)
                                + "。请确保脚本真实写入这些文件，并依赖系统自动输出的 <File> 段，而不是手动杜撰。"
                            )
                            messages.append(
                                {"role": "user", "content": warn_missing_file}
                            )
                    for prompt in post_execute_prompts:
                        messages.append({"role": "user", "content": prompt})

                    execute_rounds += 1
                    if not is_schema_code:
                        non_schema_exec_rounds += 1
                    if answer_requested:
                        answer_waiting_rounds = 0

                    # 检测代码执行错误：只要有 Traceback/Error/Exception 就警告模型
                    # 不管是否生成了文件，因为部分成功的代码仍可能包含严重错误
                    if not is_schema_code and non_schema_exec_rounds > 0:
                        has_error = any(
                            keyword in exe_output.lower()
                            for keyword in ["traceback", "error:", "exception"]
                        )
                        if has_error:
                            logger.warning(
                                f"[bot_stream] Code execution error detected (files generated: {len(artifact_paths)})"
                            )
                            # 提取错误类型和关键信息
                            error_lines = [
                                line
                                for line in exe_output.split("\n")
                                if any(
                                    kw in line.lower()
                                    for kw in ["error", "exception", "traceback"]
                                )
                            ]
                            error_hint = error_lines[-1] if error_lines else "未知错误"

                            # 特殊处理：SQL 字段错误
                            if (
                                "no such column" in exe_output.lower()
                                or "operationalerror" in exe_output.lower()
                            ):
                                # 提取表结构信息
                                schema_hint = summarize_sqlite_schema(workspace_path)
                                error_warning = (
                                    f"⚠️ SQL 查询错误：{error_hint}\n\n"
                                    "**错误原因**：代码中使用了不存在的字段名。\n\n"
                                    "**数据库真实表结构**：\n"
                                    f"{schema_hint}\n\n"
                                    "**修正方法**：\n"
                                    "1. 仔细对照上方的表结构，确认每个表的真实字段名\n"
                                    "2. 修改 SQL 查询中的字段名，使用真实存在的字段\n"
                                    "3. 不要臆测字段名，必须严格使用 sqlite_master 和 PRAGMA table_info 返回的字段\n\n"
                                    "请立即修正代码并重新提交。"
                                )
                            elif "length mismatch" in exe_output.lower():
                                error_warning = (
                                    f"⚠️ pandas 列长度不匹配：{error_hint}\n\n"
                                    "常见原因：对 describe()/transpose() 的结果强制重命名列，"
                                    "导致列数不一致。\n\n"
                                    "修正建议：\n"
                                    "1. 直接保存 describe() 结果，不要强制改列名；或\n"
                                    "2. 若只需条目数，请用两列统计表，例如：\n"
                                    "```python\n"
                                    "count_summary = pd.DataFrame({\n"
                                    "    'metric': ['disabled_count'],\n"
                                    "    'value': [len(df_disabled)],\n"
                                    "})\n"
                                    "```\n\n"
                                    "请根据上述建议修正后重新提交。"
                                )
                            elif "syntaxerror" in exe_output.lower() and (
                                "unterminated string literal" in exe_output.lower()
                                or "unterminated f-string literal" in exe_output.lower()
                            ):
                                mode_for_current = (
                                    round_mode(rule_for_current)
                                    if rule_for_current
                                    else ""
                                )
                                extra_hint = ""
                                if mode_for_current in (
                                    "html_report",
                                    "html_report_phase2",
                                ):
                                    expected_html_files = (
                                        round_expected_filenames_by_type(
                                            rule_for_current, "html"
                                        )
                                        if rule_for_current
                                        else []
                                    )
                                    expected_html_name = (
                                        expected_html_files[0]
                                        if expected_html_files
                                        else ""
                                    )
                                    expected_html_hint = (
                                        f"`generated/{expected_html_name}`"
                                        if expected_html_name
                                        else "规则要求的 HTML 文件"
                                    )
                                    extra_hint = (
                                        "\n\n**纠错提示（HTML 构造字符串未闭合）**：\n"
                                        '- 你在构造 `html_lines = [...]` 时，有某一行字符串没有正确闭合引号，或字符串意外跨行（例如写成了 `"...` 后换行）。\n'
                                        "- 常见诱因：把 `<Code>`/``` 之类的标签或示例文本误粘贴进了 `html_lines` 的字符串里，导致引号不成对。\n"
                                        "- 修正方法：\n"
                                        "  1) 确保 `html_lines` 里每个元素都是一行完整的 Python 字符串（用 `\"...\"` 或 `'...'`），不要跨行。\n"
                                        '  2) 字符串内部若包含引号，要么换用另一种引号包裹，要么用 `\\"` 转义。\n'
                                        "  3) HTML 正文里请使用 `<code>...</code>`，不要使用 `<Code>`（大写 C 的是对话标签，容易引发混淆）。\n"
                                        "  4) 最后必须写出 "
                                        + expected_html_hint
                                        + "（例如 `Path('generated') / '<文件名>'`），否则系统会继续判定缺文件。"
                                    )
                                error_warning = (
                                    f"⚠️ Python 语法错误：{error_hint}\n\n"
                                    "错误原因：字符串字面量未闭合，代码无法运行，因此不会写出 HTML 文件。"
                                    + extra_hint
                                )
                            elif (
                                "unknown format code" in exe_output.lower()
                                and "for object of type 'str'" in exe_output.lower()
                            ):
                                mode_for_current = (
                                    round_mode(rule_for_current)
                                    if rule_for_current
                                    else ""
                                )
                                extra_hint = ""
                                if mode_for_current == "html_report_phase2":
                                    extra_hint = (
                                        "\n\n**纠错提示（数值/字符串格式化）**：\n"
                                        "- 你很可能写了类似 `f\"{avg_age:.1f}\"`，但 avg_age 实际是字符串（例如你设成了 'N/A'）。\n"
                                        "- 解决方法：在写入 html_lines 前做安全格式化，例如：\n"
                                        "```python\n"
                                        "def fmt_num(x, digits=1):\n"
                                        "    try:\n"
                                        '        return f"{float(x):.{digits}f}"\n'
                                        "    except Exception:\n"
                                        "        return str(x)\n"
                                        "\n"
                                        "avg_age_str = fmt_num(avg_age, 1)\n"
                                        "avg_income_str = fmt_num(avg_income, 2)\n"
                                        "avg_loan_amount_str = fmt_num(avg_loan_amount, 2)\n"
                                        "default_rate_str = fmt_num(default_rate, 1)\n"
                                        "```\n"
                                        "- 然后在 HTML 中用 `{avg_age_str}` 等字符串变量，避免任何 `:.1f` 直接作用在可能为字符串的值上。\n"
                                        "- 修正后仍必须把规则要求的 HTML 文件写入 `generated/`（例如 `generated/comprehensive_analysis_report.html`），否则会继续被判定缺文件。"
                                    )
                                error_warning = (
                                    f"⚠️ Python 格式化错误：{error_hint}\n\n"
                                    "常见原因：对字符串使用了浮点格式化（例如 `:.1f`）。"
                                    + extra_hint
                                )
                            elif (
                                "unhashable type" in exe_output.lower()
                                and "series" in exe_output.lower()
                            ):
                                mode_for_current = (
                                    round_mode(rule_for_current)
                                    if rule_for_current
                                    else ""
                                )
                                extra_hint = ""
                                if mode_for_current == "html_report_phase2":
                                    extra_hint = (
                                        "\n\n**纠错提示（集合/去重统计）**：\n"
                                        "- 你很可能写了类似 `set([df['source'] for df in dfs])`，其中 `df['source']` 是一个 Series，无法放进 set。\n"
                                        "- 如果你想统计数据源数量：\n"
                                        "  - ✅ 用 `len(csv_files)`（每个 CSV 一个数据源），或\n"
                                        "  - ✅ 用 `combined_df['source'].nunique()`（合并后按列去重）。\n"
                                        "- 修正后仍必须把规则要求的 HTML 文件写入 `generated/` 目录，否则会继续被判定缺文件。"
                                    )
                                error_warning = (
                                    f"⚠️ Python 类型错误：{error_hint}\n\n"
                                    "常见原因：把 pandas 的 Series 当作普通标量放入 `set()`/字典 key/另一个 set，导致不可哈希。\n"
                                    "请将 Series 改为标量（例如取 `.iloc[0]`）或改用 `.nunique()` 等统计方法。"
                                    + extra_hint
                                )
                            else:
                                mode_for_current = (
                                    round_mode(rule_for_current)
                                    if rule_for_current
                                    else ""
                                )
                                html_phase2_hint = ""
                                if mode_for_current == "html_report_phase2":
                                    html_phase2_hint = (
                                        "\n\n**第 10 轮（综合 HTML 报告）纠错提示**：\n"
                                        "- 只允许读取 `generated/` 下真实存在的 CSV/PNG/README/HTML；禁止访问 `data/` 或 SQLite。\n"
                                        "- 不要对整张 DataFrame 直接 `mean()/std()`：CSV 往往混有字符串列，会触发 TypeError。\n"
                                        "- 需要数值统计时请先筛选数值列，例如：`num_df = df.select_dtypes(include='number')`，或使用 `df.mean(numeric_only=True)`。\n"
                                        "- 任何列名/字段都必须来自 `df.columns` 的真实值；先 `print(df.columns.tolist())` 再决定做哪些统计/图表，禁止假设 `loan_amount/income/region/default_rate` 等列。\n"
                                        "- 如果发现没有可用数值列：请降级为“文件清单 + 行数/缺失值 + 分类计数”等不依赖数值列的统计，并仍然生成 `comprehensive_analysis_report.html`。"
                                    )
                                error_warning = (
                                    f"代码执行过程中出现错误：{error_hint}\n\n"
                                    "请仔细检查上方 <Execute> 块中的完整错误信息，常见问题包括：\n"
                                    "1. 对字符串字段调用数值计算方法（如 df.corr()）\n"
                                    "2. 使用不存在的字段名或表名\n"
                                    "3. 数据类型不匹配\n"
                                    "4. 缺少必要的数据预处理步骤\n\n"
                                    "请修正代码后重新提交。如果部分代码已成功执行，可以基于已生成的文件继续分析。"
                                    + html_phase2_hint
                                )
                            messages.append({"role": "user", "content": error_warning})
                            allow_duplicate_analyze_retry()
                            refund_iteration()
                            refund_round_progress(is_schema_code)
                            continue

                    # 检测伪造 Execute：模型不能在自己的输出中包含 <Execute> 标签
                    # <Execute> 只能由系统在执行代码后自动生成并注入到消息历史中
                    # 注意：必须在代码执行完成后检测，这样真实的执行结果已经被注入到消息历史中
                    # 模型在下一轮就能看到真实的 <Execute> 和 <File> 块
                    if has_execute_in_raw:
                        fake_execute_warning = (
                            "检测到你在输出中包含了 <Execute> 标签。"
                            "<Execute> 块只能由系统在执行你的代码后自动生成，你不能在自己的输出中包含 <Execute> 标签。"
                            "请严格按照提示词要求：只输出 <Analyze> 和 <Code> 两个标签，"
                            "系统会自动执行代码并在下一轮消息中注入 <Execute> 和 <File> 块供你引用。"
                            "上方已经是系统自动生成的真实 <Execute> 和 <File> 块，请在下一轮基于这些真实结果继续分析。"
                        )
                        messages.append(
                            {"role": "user", "content": fake_execute_warning}
                        )
                        logger.warning(
                            f"[bot_stream] Detected fake <Execute> in model output after code execution, warning sent"
                        )
                        refund_iteration()  # 退还迭代计数，避免伪造输出被计入有效迭代
                        continue

                    # 修复22增强: 仅在代码完全通过校验后再注入下一轮任务提示
                    if not is_schema_code:
                        next_round = execute_rounds + 1
                        continue_prompt = build_continue_prompt_text(
                            execute_rounds, next_round
                        )
                        if continue_prompt:
                            rule_for_continue = get_round_rule(next_round)
                            if (
                                rule_for_continue
                                and round_mode(rule_for_continue) == "sqlite_join"
                            ):
                                expected_sqlite = find_primary_sqlite(
                                    Path(workspace_path)
                                )
                                if expected_sqlite:
                                    expected_sqlite_path = str(
                                        expected_sqlite.resolve()
                                    )
                                    continue_prompt += (
                                        "\n\n"
                                        "**【数据库绝对路径（自动注入）】后续 SQLite JOIN 必须使用：**\n\n"
                                        "```python\n"
                                        f'DB_PATH = r"{expected_sqlite_path}"\n'
                                        "```\n"
                                    )
                            logger.info(
                                f"[bot_stream] Injecting continue prompt for round {next_round}: {continue_prompt[:120]}"
                            )
                            append_user_prompt(continue_prompt)
                    if (
                        execute_rounds >= ANSWER_MIN_EXEC_ROUNDS
                        and non_schema_exec_rounds >= ANSWER_MIN_NON_SCHEMA_ROUNDS
                        and not answer_requested
                    ):
                        answer_requested = True
                        answer_waiting_rounds = 0
                        answer_prompt = (
                            "你已完成至少两轮代码执行。请停止继续编写 <Code>，在下一轮直接输出 <Answer>，"
                            "总结上述 <Execute>/<File> 结果并给出后续建议。"
                        )
                        messages.append({"role": "user", "content": answer_prompt})

                    exe_signature = (
                        re.sub(r"\s+", " ", exe_output.strip())
                        if isinstance(exe_output, str)
                        else ""
                    )
                    if (
                        schema_confirmed
                        and exe_signature
                        and last_execute_signature
                        and exe_signature == last_execute_signature
                    ):
                        repeat_prompt = "连续两轮的 <Execute> 输出完全一致（仍在列出 sqlite_master 结果）。请立即改用真实表进行 `SELECT *` 或统计分析。"
                        messages.append({"role": "user", "content": repeat_prompt})
                    last_execute_signature = exe_signature or last_execute_signature

                    normalized_output = (
                        exe_output.lower() if isinstance(exe_output, str) else ""
                    )
                    if "no such table" in normalized_output:
                        missing_match = re.search(
                            r"no such table:?\s*([\w\d_]+)", exe_output, re.IGNORECASE
                        )
                        missing_table = missing_match.group(1) if missing_match else ""
                        schema_hint = summarize_sqlite_schema(workspace_path)
                        hint_lines = [
                            "执行结果显示引用了不存在的表。请复查 sqlite_master 输出，在下一轮 <Analyze> 中说明修复计划，并改用真实表名。"
                        ]
                        if missing_table:
                            hint_lines.append(f"缺失的表：{missing_table}")
                        if schema_hint:
                            hint_lines.append(
                                "当前 workspace 中 SQLite 表结构（系统实时扫描）："
                            )
                            hint_lines.append(schema_hint)
                        messages.append(
                            {"role": "user", "content": "\n\n".join(hint_lines)}
                        )

                    current_files = {
                        str(p.resolve())
                        for p in workspace_path.rglob("*")
                        if p.is_file()
                    }
                    new_files = current_files - initial_workspace
                    if new_files:
                        initial_workspace.update(new_files)
        finally:
            if claimed_files_in_round and not code_executed:
                warn_block = emit_file_claim_warning("本轮代码未执行或已被退票")
                if warn_block:
                    assistant_reply += warn_block
                    yield warn_block

        if stop_requested:
            logger.info(
                "[bot_stream] Stop requested by user, aborting without advancing rounds"
            )
            return

        if should_stop(session_id):
            reset_stop_flag(session_id)

    if not finished and forced_reason == "" and iteration >= MAX_ITERATIONS:
        forced_reason = f"已达到最大迭代次数（{MAX_ITERATIONS}），自动结束当前任务"

    if not finished and forced_reason == "" and raw_iterations >= max_raw_iterations:
        forced_reason = f"模型经过 {raw_iterations} 次尝试仍无法生成有效输出，已达到重试上限。可能原因：模型质量不足或提示词过于复杂。建议使用更强大的模型或简化任务"

    if forced_reason and "</Answer>" not in assistant_reply:
        answer_block = f"\n<Answer>\n{forced_reason}。请参考以上 <Execute>/<File> 输出，必要时重新发起指令。\n</Answer>\n"
        assistant_reply += answer_block
        yield answer_block

    os.chdir(original_cwd)


@app.post("/chat/completions")
async def chat(body: dict = Body(...)):
    messages = body.get("messages", [])
    workspace_payload = body.get("workspace", [])
    session_id = body.get("session_id", "default")

    def generate():
        chunk_count = 0
        for delta_content in bot_stream(messages, workspace_payload, session_id):
            chunk_count += 1
            if chunk_count <= 3 or chunk_count % 10 == 0:
                print(
                    f"[chat] Yielding chunk #{chunk_count}, len={len(delta_content)}, preview={delta_content[:100] if delta_content else 'EMPTY'}"
                )
            chunk = {
                "id": "chatcmpl-stream",
                "object": "chat.completion.chunk",  # 标识为流式块
                "created": 1677652288,
                "model": MODEL_PATH,
                "choices": [
                    {
                        "index": 0,
                        # 3. 使用 delta 字段而非 message 字段
                        "delta": {
                            "content": delta_content  # 直接填入原始内容，不要调用 fix_tags
                        },
                        "finish_reason": None,  # 传输中为 None
                    }
                ],
            }

            yield json.dumps(chunk) + "\n"
            # 5. 循环结束后，发送一个结束标记 (Optional, 但推荐)
        end_chunk = {
            "id": "chatcmpl-stream",
            "object": "chat.completion.chunk",
            "created": 1677652288,
            "model": MODEL_PATH,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        yield json.dumps(end_chunk) + "\n"

    return StreamingResponse(generate(), media_type="text/plain")


@app.post("/chat/stop")
async def stop_chat(body: dict = Body(...)):
    """接收前端停止请求，设置对应 session 的中断标记。"""
    session_id = body.get("session_id", "default")
    trigger_stop_flag(session_id)
    return {"message": f"stop signal sent for {session_id}"}


# -------- Export Report (PDF + MD) --------
from datetime import datetime


def _extract_sections_from_messages(messages: list[dict]) -> str:
    """从历史消息中抽取 <Answer>..</Answer> 作为报告主体，其余部分按原始顺序作为 Appendix 拼成 Markdown。"""
    if not isinstance(messages, list):
        return ""
    import re as _re

    parts: list[str] = []
    appendix: list[str] = []

    tag_pattern = r"<(Analyze|Understand|Code|Execute|File|Answer)>([\s\S]*?)</\1>"

    for idx, m in enumerate(messages, start=1):
        role = (m or {}).get("role")
        if role != "assistant":
            continue
        content = str((m or {}).get("content") or "")

        step = 1
        # 按照在文本中的出现顺序依次提取
        for match in _re.finditer(tag_pattern, content, _re.DOTALL):
            tag, seg = match.groups()
            seg = seg.strip()
            if tag == "Answer":
                parts.append(f"{seg}\n")

            appendix.append(f"\n### Step {step}: {tag}\n\n{seg}\n")
            step += 1

    final_text = "".join(parts).strip()
    if appendix:
        final_text += (
            "\n\n\\newpage\n\n# Appendix: Detailed Process\n"
            + "".join(appendix).strip()
        )

    # print(final_text)
    return final_text


def _save_md(md_text: str, base_name: str, workspace_dir: str) -> Path:
    Path(workspace_dir).mkdir(parents=True, exist_ok=True)
    md_path = uniquify_path(Path(workspace_dir) / f"{base_name}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_text)
    return md_path


import pypandoc


def _save_pdf(md_text: str, base_name: str, workspace_dir: str) -> Path:
    Path(workspace_dir).mkdir(parents=True, exist_ok=True)
    pdf_path = uniquify_path(Path(workspace_dir) / f"{base_name}.pdf")

    output = pypandoc.convert_text(
        md_text,
        "pdf",
        format="md",
        outputfile=str(pdf_path),
        extra_args=[
            "--standalone",
            "--pdf-engine=xelatex",
        ],
    )
    return pdf_path


from typing import Optional


def _render_md_to_html(md_text: str, title: Optional[str] = None) -> str:
    """简化为占位实现（仅供未来 PDF 渲染使用）。当前仅生成 MD。"""
    doc_title = (title or "Report").strip() or "Report"
    safe = (md_text or "").replace("<", "&lt;").replace(">", "&gt;")
    return f"<html><head><meta charset='utf-8'><title>{doc_title}</title></head><body><pre>{safe}</pre></body></html>"


def _save_pdf_from_md(html_text: str, base_name: str) -> Path:
    """TODO: 服务端 PDF 渲染未实现。"""
    raise NotImplementedError("TODO: implement server-side PDF rendering")


def _save_pdf_with_chromium(html_text: str, base_name: str) -> Path:
    """TODO: 使用 Chromium 渲染 PDF（暂不实现）。"""
    raise NotImplementedError("TODO: chromium-based PDF rendering")


def _save_pdf_from_text(text: str, base_name: str) -> Path:
    """TODO: 纯文本 PDF 渲染（暂不实现）。"""
    raise NotImplementedError("TODO: text-based PDF rendering")


@app.post("/export/report")
async def export_report(body: dict = Body(...)):
    """
    接收全部聊天历史（messages: [{role, content}...]），抽取 <Analyze>..</Analyze> ~ <Answer>..</Answer>
    仅生成 Markdown 文件并保存到 workspace；PDF 渲染留作 TODO。
    """
    try:
        messages = body.get("messages", [])
        title = (body.get("title") or "").strip()
        session_id = body.get("session_id", "default")
        workspace_dir = get_session_workspace(session_id)

        if not isinstance(messages, list):
            raise HTTPException(status_code=400, detail="messages must be a list")

        md_text = _extract_sections_from_messages(messages)
        if not md_text:
            md_text = (
                "(No <Analyze>/<Understand>/<Code>/<Execute>/<Answer> sections found.)"
            )

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_title = re.sub(r"[^\w\-_.]+", "_", title) if title else "Report"
        base_name = f"{safe_title}_{ts}" if title else f"Report_{ts}"

        # Save MD into generated/ folder under workspace
        export_dir = os.path.join(workspace_dir, "generated")
        os.makedirs(export_dir, exist_ok=True)

        print(md_text)
        md_path = _save_md(md_text, base_name, export_dir)

        # PDF 暂不生成（TODO）。
        pdf_path = _save_pdf(md_text, base_name, export_dir)

        result = {
            "message": "exported",
            "md": md_path.name,
            "pdf": pdf_path.name if pdf_path else None,
            "download_urls": {
                "md": build_download_url(f"{session_id}/generated/{md_path.name}"),
                "pdf": (
                    build_download_url(f"{session_id}/generated/{pdf_path.name}")
                    if pdf_path
                    else None
                ),
            },
        }
        return JSONResponse(result)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    print("🚀 启动后端服务...")
    print(f"   - API服务: http://localhost:8200")
    print(f"   - 文件服务: http://localhost:8100")
    uvicorn.run(app, host="0.0.0.0", port=8200, log_config=None)
