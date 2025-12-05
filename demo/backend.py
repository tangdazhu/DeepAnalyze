import openai
import json
import os
import shutil
import re
import io
import contextlib
import traceback
from pathlib import Path
from urllib.parse import quote
import subprocess
import sys
import tempfile
import requests
import threading
import http.server
from functools import partial
import socketserver
import sqlite3
from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Query, Body
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional, Dict, Tuple
from collections import defaultdict
import httpx
import uvicorn
import os
import re
import json
from copy import deepcopy

PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_DIR = PROJECT_ROOT / "API"
for path_candidate in (str(PROJECT_ROOT), str(API_DIR)):
    if path_candidate not in sys.path:
        sys.path.insert(0, path_candidate)

import config as api_config

os.environ.setdefault("MPLBACKEND", "Agg")


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
MODEL_PATH = "qwen2.5-3b-instruct"  # replace to your path to DeepAnalyze-8B
MAX_ITERATIONS = 12
ANSWER_MIN_EXEC_ROUNDS = 3
ANSWER_MIN_NON_SCHEMA_ROUNDS = 2


# Initialize OpenAI client
client = openai.OpenAI(base_url=API_BASE, api_key="dummy")

# Workspace directory
WORKSPACE_BASE_DIR = "workspace"
HTTP_SERVER_PORT = 8100
MAX_PROMPT_CHARS = getattr(api_config, "MAX_PROMPT_CHARS", 16000)
HTTP_SERVER_BASE = (
    f"http://localhost:{HTTP_SERVER_PORT}"  # you can replace localhost to your local ip
)


def get_session_workspace(session_id: str) -> str:
    """返回指定 session 的 workspace 路径（workspace/{session_id}/）。"""
    if not session_id:
        session_id = "default"
    session_dir = os.path.join(WORKSPACE_BASE_DIR, session_id)
    os.makedirs(session_dir, exist_ok=True)
    return session_dir


def build_download_url(rel_path: str) -> str:
    try:
        encoded = quote(rel_path, safe="/")
    except Exception:
        encoded = rel_path
    return f"{HTTP_SERVER_BASE}/{encoded}"


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


def extract_table_mentions_from_text(
    text: str, known_tables: set[str]
) -> tuple[set[str], set[str]]:
    tokens = set(TABLE_TOKEN_PATTERN.findall(text or ""))
    known = {tok for tok in tokens if tok in known_tables}
    unknown = {
        tok
        for tok in tokens
        if tok not in known_tables
        and "_" in tok
        and tok.lower() not in {"sqlite_master", "sqlite_sequence"}
    }
    return known, unknown


def extract_sql_table_names(code: str) -> set[str]:
    tables = set(SQL_TABLE_PATTERN.findall(code or ""))
    tables.update(SQL_PRAGMA_PATTERN.findall(code or ""))
    return tables


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
FILE_NAME_PATTERN = re.compile(
    r"([\w\-.]+\.(?:csv|tsv|txt|md|json|png|jpg|jpeg|gif|svg|pdf|xlsx|xls|parquet))",
    re.IGNORECASE,
)
FILENAME_SUFFIX_CLEANER = re.compile(r"\s+\(\d+\)$")


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


def normalize_model_tags(content: str) -> str:
    """将常见的 emoji 标签转换为标准 <Tag> 形式。"""
    if not content:
        return content
    normalized = content
    for emoji_tag, canonical in EMOJI_TAG_MAP.items():
        normalized = normalized.replace(emoji_tag, canonical)
    normalized = HEADING_TAG_PATTERN.sub(lambda m: f"<{m.group(1)}>", normalized)
    return normalized


SQLITE_PATTERNS = ("*.sqlite", "*.db", "*.db3")


def find_primary_sqlite(workspace_path: Path) -> Path | None:
    """在 workspace 中（递归）定位首个 sqlite 文件。"""
    for pattern in SQLITE_PATTERNS:
        try:
            candidates = sorted(workspace_path.rglob(pattern))
        except Exception:
            candidates = []
        for file in candidates:
            if file.is_file():
                return file
    return None


def build_schema_bootstrap_block(workspace_path: Path) -> str:
    """生成首轮自动列出 sqlite_master 的模板响应。"""
    db_path = find_primary_sqlite(workspace_path)
    if not db_path:
        return ""
    try:
        rel_path = db_path.resolve().relative_to(workspace_path.resolve())
        db_name = rel_path.as_posix()
    except Exception:
        db_name = db_path.name
    analyze = (
        "<Analyze>\n"
        "系统检测到模型尚未正确进入首轮分析，已自动补充：当前目标=列出所有表结构，"
        "并在同轮 <Execute> 中打印 sqlite_master 结果，供后续引用。\n"
        "</Analyze>\n"
    )
    query_lines = "\n".join(
        [
            "SELECT name AS table_name, type, sql",
            "FROM sqlite_master",
            "WHERE type IN ('table', 'view');",
        ]
    )
    code = (
        "<Code>\n"
        "```python\n"
        "import sqlite3\n"
        "import pandas as pd\n"
        "\n"
        f'conn = sqlite3.connect(r"{db_name}")\n'
        f'query = """\n{query_lines}\n"""\n'
        "schema_df = pd.read_sql_query(query, conn)\n"
        "print(schema_df)\n"
        "conn.close()\n"
        "```\n"
        "</Code>"
    )
    return analyze + "\n" + code


def run_schema_bootstrap(workspace_path: Path) -> str:
    """执行首轮 schema 查询并返回完整 <Analyze>/<Code>/<Execute> 块。"""
    block = build_schema_bootstrap_block(workspace_path)
    if not block:
        return ""
    code_match = re.search(r"```python(.*?)```", block, re.DOTALL)
    script = code_match.group(1).strip() if code_match else ""
    if not script:
        return block
    output = execute_code_safe(script, str(workspace_path))
    exe_block = f"\n<Execute>\n```\n{output}\n```\n</Execute>\n"
    file_block = "\n<File>\n暂无文件\n</File>\n"
    return f"{block}{exe_block}{file_block}"


def extract_effective_code(code_str: str) -> str:
    """若 <Code> 中包裹三引号字符串，提取其中的实际脚本内容。"""
    if not code_str:
        return ""
    for quote in ('"""', "'''"):
        start = code_str.find(quote)
        if start != -1:
            end = code_str.find(quote, start + 3)
            if end != -1:
                inner = code_str[start + 3 : end].strip()
                # 如果内层脚本仍包含 import / SELECT 等关键字，则认为是有效脚本
                if any(
                    token in inner
                    for token in ["import", "select", "plt.", "sns.", "pd."]
                ):
                    return inner
    return code_str


def bot_stream(messages, workspace, session_id="default"):
    original_cwd = os.getcwd()
    workspace_path = Path(get_session_workspace(session_id)).resolve()
    workspace_path.mkdir(parents=True, exist_ok=True)
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

    last_code_signature = None
    last_analyze_signature = None
    last_execute_signature = None
    schema_confirmed = False
    schema_only_repeat = 0
    execute_rounds = 0
    non_schema_exec_rounds = 0
    answer_requested = False
    answer_waiting_rounds = 0
    known_tables = list_sqlite_tables(workspace_path)
    recent_tables_used: set[str] = set()
    schema_summary_injected = False
    schema_bootstrap_used = False

    def refund_iteration():
        nonlocal iteration
        iteration = max(0, iteration - 1)

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

    while (
        not finished
        and iteration < MAX_ITERATIONS
        and raw_iterations < max_raw_iterations
    ):
        raw_iterations += 1
        iteration += 1
        print(
            f"[bot_stream] session={session_id} iteration={iteration} raw={raw_iterations} starting, messages={len(messages)}"
        )
        safe_messages = trim_messages(messages)

        response = client.chat.completions.create(
            model=MODEL_PATH,
            messages=safe_messages,
            temperature=0.4,
            stream=True,
            extra_body={
                "add_generation_prompt": False,
                "stop_token_ids": [151676, 151645],
                "max_new_tokens": 4096,
            },
        )
        cur_res = ""
        last_finish_reason = None
        for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content is not None:
                delta = chunk.choices[0].delta.content
                cur_res += delta
                assistant_reply += delta
                yield delta
            if chunk.choices and chunk.choices[0].finish_reason:
                last_finish_reason = chunk.choices[0].finish_reason
            if should_stop(session_id):
                stop_msg = "\n<Execute>\n``````\n检测到停止指令，正在安全结束当前迭代。\n```\n</Execute>\n"
                assistant_reply += stop_msg
                yield stop_msg
                forced_reason = "任务已根据用户的停止指令终止"
                finished = True
                break
            if "</Answer>" in cur_res:
                if non_schema_exec_rounds == 0:
                    messages.append({"role": "assistant", "content": cur_res})
                    warn_msg = "尚未基于真实表执行任何 EDA/可视化。请先按照要求运行 `SELECT *` 等分析，形成 <Execute>/<File> 结果后再给出 <Answer>。"
                    messages.append({"role": "user", "content": warn_msg})
                    cur_res = cur_res.replace("<Answer>", "<Answer (ignored)>")
                else:
                    finished = True
                    break

        cur_res = normalize_model_tags(cur_res)
        fixed_res = fix_tags_and_codeblock(cur_res)
        if fixed_res != cur_res:
            extra_text = fixed_res[len(cur_res) :]
            if extra_text:
                assistant_reply += extra_text
                yield extra_text
            cur_res = fixed_res

        print(
            f"[bot_stream] session={session_id} iteration={iteration} finish_reason={last_finish_reason} has_code={'<Code>' in cur_res} closed={'</Code>' in cur_res} len={len(cur_res)}"
        )

        analyze_match = re.search(r"<Analyze>(.*?)</Analyze>", cur_res, re.DOTALL)
        analyze_content = analyze_match.group(1).strip() if analyze_match else ""
        analyze_signature = (
            re.sub(r"\s+", " ", analyze_content) if analyze_content else ""
        )

        if not analyze_content:
            messages.append({"role": "assistant", "content": cur_res})
            if not schema_confirmed and not schema_bootstrap_used:
                auto_block = run_schema_bootstrap(workspace_path)
                if auto_block:
                    schema_bootstrap_used = True
                    schema_confirmed = True
                    latest_tables = list_sqlite_tables(workspace_path)
                    if latest_tables:
                        known_tables = latest_tables
                    assistant_reply += auto_block
                    yield auto_block
                    messages.append({"role": "assistant", "content": auto_block})
                    continue
            analyze_prompt = "你的输出缺少 <Analyze> 段，必须先在 <Analyze> 中说明当前目标与依据，再给出 <Code>。"
            messages.append({"role": "user", "content": analyze_prompt})
            refund_iteration()
            continue

        if (
            schema_confirmed
            and "列出" in analyze_content
            and "表结构" in analyze_content
        ):
            messages.append({"role": "assistant", "content": cur_res})
            advance_prompt = "表结构已在首轮列出，请基于已知表/字段提出新的分析目标，换用真实查询或 EDA 任务。"
            messages.append({"role": "user", "content": advance_prompt})
            refund_iteration()
            continue

        if last_analyze_signature and analyze_signature == last_analyze_signature:
            messages.append({"role": "assistant", "content": cur_res})
            diff_prompt = "你的 <Analyze> 内容与上一轮完全相同，请结合最新的 <Execute>/<File> 结果提出不同的分析步骤。"
            messages.append({"role": "user", "content": diff_prompt})
            refund_iteration()
            continue

        known_mentions = set()
        unknown_mentions = set()
        require_known_reference = schema_confirmed and non_schema_exec_rounds == 0
        if known_tables:
            known_mentions, unknown_mentions = extract_table_mentions_from_text(
                analyze_content, known_tables
            )
            if schema_confirmed and unknown_mentions:
                messages.append({"role": "assistant", "content": cur_res})
                warn_unknown = (
                    "检测到你引用了不存在于实际 SQLite 中的表："
                    + ", ".join(sorted(unknown_mentions))
                    + "。请重新查看 sqlite_master 结果，仅使用真实表名。"
                )
                messages.append({"role": "user", "content": warn_unknown})
                refund_iteration()
                continue
            if require_known_reference and not known_mentions:
                messages.append({"role": "assistant", "content": cur_res})
                table_samples = sorted(known_tables)
                sample_hint = (
                    ", ".join(table_samples[:3]) if table_samples else "真实表"
                )
                ref_prompt = (
                    "请在 <Analyze> 中引用 sqlite_master 返回的真实表名（如："
                    + sample_hint
                    + "），并结合这些表/字段制定下一步分析计划。"
                )
                messages.append({"role": "user", "content": ref_prompt})
                refund_iteration()
                continue

        last_analyze_signature = analyze_signature

        if not cur_res.strip() and not finished:
            empty_retry += 1
            if empty_retry < 3:
                retry_prompt = (
                    "上一轮你没有任何输出，请继续按照既定计划进行分析，"
                    "务必给出 <Analyze>/<Code>/<Execute> 的完整内容。"
                )
                messages.append({"role": "user", "content": retry_prompt})
                continue
            forced_reason = "连续多轮未返回新增内容，已终止本轮迭代"
            finished = True
            break
        else:
            empty_retry = 0

        if finished:
            break

        has_code_block = "<Code>" in cur_res and "</Code>" in cur_res

        if not has_code_block:
            messages.append({"role": "assistant", "content": cur_res})
            if answer_requested:
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
                code_prompt = (
                    "你的输出缺少 <Code> 段。请在 <Analyze> 后立刻提供完整的 Python 代码（含 import/连接/EDA/plt 保存/conn.close()），"
                    "以便系统执行。"
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
                correction_prompt = (
                    "你必须严格按如下结构输出：先用 <Analyze> 拆解任务，紧接着在 <Code> 中给出可执行的"
                    " Python 代码（使用 ```python ... ``` 包裹），等待系统执行，再结合 <Execute>/<File> 结果"
                    " 继续分析。不要重复欢迎语，立刻补充缺失的 <Code>。"
                )
                messages.append({"role": "user", "content": correction_prompt})
                continue

        claimed_files_in_round = extract_file_claims(cur_res)

        if "</Code>" in cur_res and not finished:
            if answer_requested:
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
            messages.append({"role": "assistant", "content": cur_res})
            code_match = re.search(r"<Code>(.*?)</Code>", cur_res, re.DOTALL)
            if code_match:
                code_content = code_match.group(1).strip()
                md_match = re.search(r"```(?:python)?(.*?)```", code_content, re.DOTALL)
                code_str = md_match.group(1).strip() if md_match else code_content
                effective_code = extract_effective_code(code_str)

                code_signature = "\n".join(
                    line.strip() for line in effective_code.splitlines()
                ).strip()
                normalized_code = effective_code.lower()
                if code_signature and code_signature == last_code_signature:
                    reminder = (
                        "你的代码与上一轮完全相同。请根据已获取的表结构推进新的分析，"
                        "不要重复列出 sqlite_master。"
                    )
                    messages.append({"role": "user", "content": reminder})
                    refund_iteration()
                    continue
                if (
                    schema_confirmed
                    and "sqlite_master" in normalized_code
                    and "pragma" not in normalized_code
                ):
                    schema_only_repeat += 1
                    table_examples = sorted(known_tables)
                    example_text = (
                        ", ".join(table_examples[:3]) if table_examples else "真实表"
                    )
                    sample_next = (
                        f"例如：SELECT * FROM {table_examples[0]} LIMIT 5"
                        if table_examples
                        else "例如：SELECT * FROM 某个真实表 LIMIT 5"
                    )
                    refresh_prompt = (
                        "表结构已经明确，无需再次查询 sqlite_master。请直接对真实表（如："
                        + example_text
                        + f"）执行 SELECT/EDA，比如 {sample_next} 或绘制对应字段的分布。"
                    )
                    if schema_only_repeat >= 2:
                        violation_block = (
                            "\n<Answer>\n已确认表结构后仍连续输出 sqlite_master 查询，任务被自动终止。"
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
                    }

                post_execute_prompts: list[str] = []
                if schema_confirmed and invalid_tables:
                    invalid_msg = (
                        "脚本中引用了系统尚未确认的表："
                        + ", ".join(sorted(invalid_tables))
                        + "。系统会尝试执行以验证其是否真实存在；若下一轮 <Execute> 报错，请优先回到 sqlite_master/PRAGMA 重新核对表名。"
                    )
                    post_execute_prompts.append(invalid_msg)

                if not schema_confirmed and "sqlite_master" not in normalized_code:
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
                if missing_imports:
                    import_prompt = (
                        "检测到 <Code> 使用了 pandas/matplotlib/seaborn，但缺少以下导入："
                        + ", ".join(missing_imports)
                        + "。请补全导入后再执行。"
                    )
                    messages.append({"role": "user", "content": import_prompt})
                    refund_iteration()
                    continue

                if "import sqlite3" not in effective_code:
                    sqlite_prompt = (
                        "每个 <Code> 脚本都需显式 `import sqlite3` 并建立数据库连接。"
                        " 请将完整脚本补全（含 import / connect / 执行 / close）后再运行。"
                    )
                    messages.append({"role": "user", "content": sqlite_prompt})
                    refund_iteration()
                    continue

                if "sqlite3.connect" not in effective_code:
                    connect_prompt = (
                        "检测到代码缺少 `sqlite3.connect(...)`，而本系统每次执行都会在独立进程运行，"
                        "不能复用上一轮连接。请在 <Code> 中创建并关闭连接后重新提交。"
                    )
                    messages.append({"role": "user", "content": connect_prompt})
                    refund_iteration()
                    continue

                last_code_signature = code_signature

                print(
                    f"[bot_stream] session={session_id} iteration={iteration} executing code, length={len(code_str)}"
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

                is_schema_code = (
                    "sqlite_master" in normalized_code
                    and "pragma" not in normalized_code
                )

                if not schema_confirmed and "sqlite_master" in normalized_code:
                    schema_confirmed = True
                    latest_tables = list_sqlite_tables(workspace_path)
                    if latest_tables:
                        known_tables = latest_tables
                    if not schema_summary_injected:
                        schema_hint = summarize_sqlite_schema(workspace_path)
                        if schema_hint:
                            schema_summary = (
                                "系统已从实际 sqlite_master/PRAGMA 中解析到以下表结构，请在后续 <Analyze>/<Code> 中"
                                " 直接引用这些真实名字，并按其中字段推进分析：\n"
                                f"{schema_hint}\n"
                                "下一步建议：从上述表中任选一个（如第一张表）执行 `SELECT * ... LIMIT 50` 做初步概览。"
                            )
                            messages.append({"role": "user", "content": schema_summary})
                        schema_summary_injected = True

                try:
                    after_state = {
                        p.resolve(): (p.stat().st_size, p.stat().st_mtime_ns)
                        for p in workspace_path.rglob("*")
                        if p.is_file()
                    }
                except Exception:
                    after_state = {}

                added_paths = [p for p in after_state.keys() if p not in before_state]
                modified_paths = [
                    p
                    for p in after_state.keys()
                    if p in before_state and after_state[p] != before_state[p]
                ]

                artifact_paths = []
                generated_dir_str = str(generated_dir.resolve())
                for p in added_paths:
                    try:
                        if not str(p).startswith(generated_dir_str):
                            dest_path = uniquify_path(generated_dir / p.name)
                            shutil.copy2(p, dest_path)
                            artifact_paths.append(dest_path.resolve())
                        else:
                            artifact_paths.append(p.resolve())
                    except Exception as e:
                        print(f"Error moving file {p}: {e}")

                for p in modified_paths:
                    try:
                        dest_path = uniquify_path(
                            generated_dir / f"{p.stem}_modified{p.suffix}"
                        )
                        shutil.copy2(p, dest_path)
                        artifact_paths.append(dest_path.resolve())
                    except Exception as e:
                        print(f"Error copying modified file {p}: {e}")

                exe_str = f"\n<Execute>\n```\n{exe_output}\n```\n</Execute>\n"
                actual_files = {
                    normalize_filename(Path(p).name) for p in artifact_paths
                }
                file_block_lines = ["<File>"]
                if artifact_paths:
                    for p in artifact_paths:
                        try:
                            rel = p.resolve().relative_to(workspace_path).as_posix()
                        except Exception:
                            rel = p.name
                        url = build_download_url(f"{session_id}/{rel}")
                        name = p.name
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
                        warn_missing_file = (
                            "系统未检测到你在 <File> 中声明的文件："
                            + ", ".join(unmatched_claims)
                            + "。请确保脚本真实写入这些文件，并依赖系统自动输出的 <File> 段，而不是手动杜撰。"
                        )
                        messages.append({"role": "user", "content": warn_missing_file})
                for prompt in post_execute_prompts:
                    messages.append({"role": "user", "content": prompt})

                execute_rounds += 1
                if not is_schema_code:
                    non_schema_exec_rounds += 1
                if answer_requested:
                    answer_waiting_rounds = 0
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
                    str(p.resolve()) for p in workspace_path.rglob("*") if p.is_file()
                }
                new_files = current_files - initial_workspace
                if new_files:
                    initial_workspace.update(new_files)

        if should_stop(session_id) and not forced_reason:
            forced_reason = "任务已根据用户的停止指令终止"
            finished = True
            break

    if not finished and forced_reason == "" and iteration >= MAX_ITERATIONS:
        forced_reason = f"已达到最大迭代次数（{MAX_ITERATIONS}），自动结束当前任务"

    if forced_reason and "</Answer>" not in assistant_reply:
        answer_block = f"\n<Answer>\n{forced_reason}。请参考以上 <Execute>/<File> 输出，必要时重新发起指令。\n</Answer>\n"
        assistant_reply += answer_block
        yield answer_block

    os.chdir(original_cwd)


@app.post("/chat/completions")
async def chat(body: dict = Body(...)):
    messages = body.get("messages", [])
    workspace = body.get("workspace", [])
    session_id = body.get("session_id", "default")

    def generate():
        for delta_content in bot_stream(messages, workspace, session_id):
            # print(delta_content)
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
    uvicorn.run(app, host="0.0.0.0", port=8200)
