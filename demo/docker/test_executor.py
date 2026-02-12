"""Docker 执行器独立测试脚本。

用法：
    cd demo
    python docker/test_executor.py

前置条件：
    1. Docker Engine 已启动
    2. 已构建镜像: docker build -t deepanalyze-sandbox:latest docker/
"""

import sys
import tempfile
from pathlib import Path

# 将 demo/ 加入 sys.path 以导入 docker_executor
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from docker_executor import check_docker_available, check_image_exists, execute_in_docker

IMAGE = "deepanalyze-sandbox:latest"
PASSED = 0
FAILED = 0


def run_test(
    name: str,
    code: str,
    workspace_dir: str,
    expect_in_output: list[str] | None = None,
    expect_not_in_output: list[str] | None = None,
    timeout_sec: int = 30,
) -> None:
    """执行单个测试用例并校验输出。"""
    global PASSED, FAILED
    print(f"\n{'='*60}")
    print(f"测试: {name}")
    print(f"{'='*60}")
    output = execute_in_docker(code, workspace_dir, IMAGE, timeout_sec=timeout_sec)
    print(f"输出:\n{output}")

    ok = True
    if expect_in_output:
        for s in expect_in_output:
            if s not in output:
                print(f"  ❌ 期望输出包含 '{s}'，但未找到")
                ok = False
    if expect_not_in_output:
        for s in expect_not_in_output:
            if s in output:
                print(f"  ❌ 期望输出不包含 '{s}'，但找到了")
                ok = False
    if ok:
        print(f"  ✅ 通过")
        PASSED += 1
    else:
        FAILED += 1


def main() -> None:
    global PASSED, FAILED

    # 前置检查
    print("检查 Docker 可用性...")
    if not check_docker_available():
        print("❌ Docker 不可用，请先启动 Docker Engine")
        sys.exit(1)
    print("  ✅ Docker 可用")

    print("检查镜像存在...")
    if not check_image_exists(IMAGE):
        print(f"❌ 镜像 {IMAGE} 不存在，请先构建:")
        print(f"   cd demo/docker && docker build -t {IMAGE} .")
        sys.exit(1)
    print(f"  ✅ 镜像 {IMAGE} 存在")

    # 创建临时 workspace
    with tempfile.TemporaryDirectory(prefix="deepanalyze_test_") as tmpdir:
        ws = Path(tmpdir)
        (ws / "data").mkdir()
        (ws / "generated").mkdir()
        # 写入测试数据
        (ws / "data" / "test.csv").write_text(
            "a,b\n1,2\n3,4\n", encoding="utf-8"
        )

        # 测试 1: 基础输出
        run_test(
            "基础 print",
            'print("hello sandbox")',
            str(ws),
            expect_in_output=["hello sandbox"],
        )

        # 测试 2: 读取 CSV
        run_test(
            "读取 CSV",
            (
                "import pandas as pd\n"
                "df = pd.read_csv('data/test.csv')\n"
                "print('rows:', len(df))"
            ),
            str(ws),
            expect_in_output=["rows: 2"],
        )

        # 测试 3: 写入 generated/
        run_test(
            "写入文件到 generated/",
            (
                "from pathlib import Path\n"
                "Path('generated/result.txt').write_text('ok')\n"
                "print('written')"
            ),
            str(ws),
            expect_in_output=["written"],
        )
        # 验证宿主机文件
        result_file = ws / "generated" / "result.txt"
        if result_file.exists() and result_file.read_text() == "ok":
            print("  ✅ 宿主机文件验证通过")
        else:
            print("  ❌ 宿主机文件验证失败")
            FAILED += 1
            PASSED -= 1  # 修正计数（run_test 已经 +1）

        # 测试 4: matplotlib 生成 PNG
        run_test(
            "matplotlib 生成 PNG",
            (
                "import matplotlib\n"
                "matplotlib.use('Agg')\n"
                "import matplotlib.pyplot as plt\n"
                "plt.figure()\n"
                "plt.plot([1,2,3],[1,4,9])\n"
                "plt.savefig('generated/test.png', dpi=72)\n"
                "print('png saved')"
            ),
            str(ws),
            expect_in_output=["png saved"],
        )
        png_file = ws / "generated" / "test.png"
        if png_file.exists() and png_file.stat().st_size > 1000:
            print(f"  ✅ PNG 文件验证通过 ({png_file.stat().st_size} bytes)")
        else:
            size = png_file.stat().st_size if png_file.exists() else 0
            print(f"  ❌ PNG 文件验证失败 (exists={png_file.exists()}, size={size})")
            FAILED += 1
            PASSED -= 1

        # 测试 5: 错误处理
        run_test(
            "异常捕获（ZeroDivisionError）",
            "print(1/0)",
            str(ws),
            expect_in_output=["ZeroDivisionError"],
        )

        # 测试 6: 超时处理
        run_test(
            "超时处理",
            "import time; time.sleep(60)",
            str(ws),
            expect_in_output=["Timeout"],
            timeout_sec=5,
        )

    # 汇总
    print(f"\n{'='*60}")
    print(f"测试结果: {PASSED} 通过, {FAILED} 失败")
    print(f"{'='*60}")
    sys.exit(1 if FAILED > 0 else 0)


if __name__ == "__main__":
    main()
