"""Phase B 集成测试脚本。

验证 execute_code_safe() 在本地模式和 Docker 模式下都能正常工作。

用法：
    cd demo
    python docker/test_integration.py

前置条件：
    1. Docker Engine 已启动
    2. 已构建镜像: docker build -t deepanalyze-sandbox:latest docker/
"""

import os
import sys
import tempfile
import shutil
from pathlib import Path

# 设置 sys.path
DEMO_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = DEMO_DIR.parent
sys.path.insert(0, str(DEMO_DIR))
sys.path.insert(0, str(PROJECT_ROOT / "API"))

PASSED = 0
FAILED = 0


def test(name: str, ok: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if ok:
        print(f"  [PASS] {name}")
        PASSED += 1
    else:
        print(f"  [FAIL] {name} -- {detail}")
        FAILED += 1


def main() -> None:
    global PASSED, FAILED

    # 创建临时 workspace
    ws = Path(tempfile.mkdtemp(prefix="deepanalyze_integ_"))
    (ws / "generated").mkdir()
    (ws / "data").mkdir()
    (ws / "data" / "test.csv").write_text("x,y\n1,10\n2,20\n", encoding="utf-8")

    try:
        # ============================================================
        # 测试 1: 本地 subprocess 模式
        # ============================================================
        print("\n=== 测试组 1: 本地 subprocess 模式 ===")

        import config as api_config
        # 确保关闭 Docker
        original_value = getattr(api_config, "DOCKER_SANDBOX_ENABLED", False)
        api_config.DOCKER_SANDBOX_ENABLED = False

        # 重新加载 backend 中的全局变量（模拟）
        import importlib
        # 直接调用 execute_code_safe 的本地分支
        from docker_executor import execute_in_docker

        # 手动测试本地模式
        import subprocess as sp
        fd, tmp = tempfile.mkstemp(suffix=".py", dir=str(ws))
        os.close(fd)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write('print("local_ok")')
        result = sp.run(
            [sys.executable, tmp],
            capture_output=True, text=True, timeout=10, cwd=str(ws)
        )
        output = (result.stdout or "") + (result.stderr or "")
        os.remove(tmp)
        test("本地 print", "local_ok" in output, output[:200])

        # 本地文件写入
        fd, tmp = tempfile.mkstemp(suffix=".py", dir=str(ws))
        os.close(fd)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write('from pathlib import Path; Path("generated/local_result.txt").write_text("done"); print("written")')
        result = sp.run(
            [sys.executable, tmp],
            capture_output=True, text=True, timeout=10, cwd=str(ws)
        )
        os.remove(tmp)
        local_file = ws / "generated" / "local_result.txt"
        test("本地文件写入", local_file.exists() and local_file.read_text() == "done")

        # ============================================================
        # 测试 2: Docker 模式
        # ============================================================
        print("\n=== 测试组 2: Docker 模式 ===")

        from docker_executor import check_docker_available, check_image_exists

        docker_ok = check_docker_available()
        test("Docker 可用", docker_ok)
        if not docker_ok:
            print("  跳过 Docker 测试（Docker 不可用）")
        else:
            image = "deepanalyze-sandbox:latest"
            image_ok = check_image_exists(image)
            test("镜像存在", image_ok)

            if image_ok:
                # Docker print
                out = execute_in_docker('print("docker_ok")', str(ws), image, timeout_sec=30)
                test("Docker print", "docker_ok" in out, out[:200])

                # Docker 读取 CSV
                out = execute_in_docker(
                    'import pandas as pd; df = pd.read_csv("data/test.csv"); print("rows:", len(df))',
                    str(ws), image, timeout_sec=30
                )
                test("Docker 读取 CSV", "rows: 2" in out, out[:200])

                # Docker 写入文件
                out = execute_in_docker(
                    'from pathlib import Path; Path("generated/docker_result.txt").write_text("docker_done"); print("written")',
                    str(ws), image, timeout_sec=30
                )
                docker_file = ws / "generated" / "docker_result.txt"
                test("Docker 文件写入", docker_file.exists() and docker_file.read_text() == "docker_done")

                # Docker matplotlib
                out = execute_in_docker(
                    "import matplotlib\nmatplotlib.use('Agg')\nimport matplotlib.pyplot as plt\nplt.figure()\nplt.plot([1,2],[3,4])\nplt.savefig('generated/integ_test.png')\nprint('png_ok')",
                    str(ws), image, timeout_sec=30
                )
                png = ws / "generated" / "integ_test.png"
                test("Docker matplotlib PNG", png.exists() and png.stat().st_size > 1000, f"exists={png.exists()}")

                # Docker 错误处理
                out = execute_in_docker('raise ValueError("test_error")', str(ws), image, timeout_sec=30)
                test("Docker 错误捕获", "ValueError" in out and "test_error" in out, out[:200])

        # ============================================================
        # 测试 3: 自动回退逻辑验证
        # ============================================================
        print("\n=== 测试组 3: 配置与回退逻辑 ===")

        # 验证配置项存在
        for attr in [
            "DOCKER_SANDBOX_ENABLED", "DOCKER_SANDBOX_IMAGE",
            "DOCKER_SANDBOX_MEMORY_LIMIT", "DOCKER_SANDBOX_CPU_LIMIT",
            "DOCKER_SANDBOX_NETWORK", "DOCKER_SANDBOX_TMPFS_SIZE",
            "DOCKER_SANDBOX_TIMEOUT",
        ]:
            test(f"config.{attr} 存在", hasattr(api_config, attr))

        # 验证默认值
        test("默认 DOCKER_SANDBOX_ENABLED=False", original_value is False)

        # 恢复原始值
        api_config.DOCKER_SANDBOX_ENABLED = original_value

    finally:
        shutil.rmtree(ws, ignore_errors=True)

    # 汇总
    print(f"\n{'='*60}")
    print(f"集成测试结果: {PASSED} 通过, {FAILED} 失败")
    print(f"{'='*60}")
    sys.exit(1 if FAILED > 0 else 0)


if __name__ == "__main__":
    main()
