"""Docker 沙箱代码执行器。

通过 docker run 在隔离容器中执行模型生成的 Python 代码。
容器生命周期：每次执行创建 → 运行 → 销毁（--rm），无状态。

配置项从 API/config.py 读取，以 DOCKER_SANDBOX_ 为前缀。
"""

import logging
import os
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger("deepanalyze.docker_executor")


def check_docker_available() -> bool:
    """检查 Docker Engine 是否可用。"""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def check_image_exists(image: str) -> bool:
    """检查指定 Docker 镜像是否存在。"""
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def execute_in_docker(
    code_str: str,
    workspace_dir: str,
    image: str,
    timeout_sec: int = 120,
    memory_limit: str = "2g",
    cpu_limit: str = "2.0",
    network: str = "none",
    tmpfs_size: str = "256m",
) -> str:
    """在 Docker 容器中执行 Python 代码。

    Args:
        code_str: 要执行的 Python 代码字符串
        workspace_dir: 宿主机 workspace 绝对路径（挂载到容器 /data）
        image: Docker 镜像名称
        timeout_sec: 执行超时（秒）
        memory_limit: 内存上限（如 "2g"）
        cpu_limit: CPU 核数上限（如 "2.0"）
        network: 网络模式（"none" 禁用网络, "bridge" 允许网络）
        tmpfs_size: /tmp 大小

    Returns:
        stdout + stderr 合并输出
    """
    workspace_path = Path(workspace_dir).resolve()
    generated_dir = workspace_path / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)

    # 将代码写入 generated/ 下的临时文件（容器内可通过 /data/generated/ 访问）
    fd, tmp_path = tempfile.mkstemp(suffix=".py", dir=str(generated_dir))
    os.close(fd)
    tmp_name = Path(tmp_path).name

    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(code_str)

        # 构建 docker run 命令
        # workspace/ 整体挂载为 /data（读写），代码在 /data 下执行
        container_script = f"/data/generated/{tmp_name}"

        cmd = [
            "docker", "run", "--rm",
            # 资源限制
            f"--memory={memory_limit}",
            f"--cpus={cpu_limit}",
            # 网络隔离
            f"--network={network}",
            # 临时文件系统
            f"--tmpfs=/tmp:size={tmpfs_size}",
            # 安全：禁止提权
            "--security-opt=no-new-privileges",
            # 只读根文件系统（/data 除外）
            "--read-only",
            # 挂载 workspace → /data（读写，因为需要写入 generated/）
            "-v", f"{workspace_path}:/data",
            # 工作目录
            "-w", "/data",
            # 镜像
            image,
            # 执行命令
            "python", container_script,
        ]

        logger.info(
            "[docker_exec] Running: image=%s, script=%s, timeout=%ss, mem=%s, cpu=%s",
            image, tmp_name, timeout_sec, memory_limit, cpu_limit,
        )

        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec + 10,  # 额外 10s 给容器启动/销毁
        )

        output = (completed.stdout or "") + (completed.stderr or "")

        if completed.returncode != 0 and not output.strip():
            output = f"[Error]: Container exited with code {completed.returncode}"

        return output

    except subprocess.TimeoutExpired:
        logger.warning(
            "[docker_exec] Timeout after %ss for script %s", timeout_sec, tmp_name
        )
        return f"[Timeout]: execution exceeded {timeout_sec} seconds"
    except FileNotFoundError:
        logger.error(
            "[docker_exec] Docker command not found. Is Docker installed?"
        )
        return "[Error]: Docker is not installed or not in PATH"
    except Exception as e:
        logger.error("[docker_exec] Unexpected error: %s", e)
        return f"[Error]: {str(e)}"
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
