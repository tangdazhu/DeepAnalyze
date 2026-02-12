"""端到端验证路径重写 + Docker 执行。"""

import sys
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "API"))

from docker_executor import execute_in_docker, check_docker_available, check_image_exists

PASSED = 0
FAILED = 0


def test(name, ok, detail=""):
    global PASSED, FAILED
    if ok:
        print(f"  [PASS] {name}")
        PASSED += 1
    else:
        print(f"  [FAIL] {name} -- {detail}")
        FAILED += 1


def main():
    global PASSED, FAILED

    if not check_docker_available():
        print("Docker 不可用，跳过测试")
        return
    if not check_image_exists("deepanalyze-sandbox:latest"):
        print("镜像不存在，跳过测试")
        return

    ws = Path(tempfile.mkdtemp(prefix="deepanalyze_rewrite_"))
    (ws / "generated").mkdir()
    (ws / "test.csv").write_text("name,school\nAlice,MIT\nBob,Stanford\n", encoding="utf-8")
    (ws / "test.sqlite").write_bytes(b"")  # 占位

    image = "deepanalyze-sandbox:latest"
    host_ws = str(ws.resolve())

    try:
        print(f"\n=== 测试路径重写 (workspace={host_ws}) ===\n")

        # 测试 1: 使用宿主机绝对路径读取 CSV（应被重写为 /data）
        code1 = f'''import pandas as pd
df = pd.read_csv(r"{host_ws}/test.csv")
print("rows:", len(df))
print("cols:", list(df.columns))
'''
        out1 = execute_in_docker(code1, host_ws, image, timeout_sec=30)
        test("宿主机路径 CSV 读取（路径重写）", "rows: 2" in out1, out1[:300])

        # 测试 2: 使用宿主机绝对路径写入文件
        code2 = f'''from pathlib import Path
Path(r"{host_ws}/generated/rewrite_test.txt").write_text("rewrite_ok")
print("written")
'''
        out2 = execute_in_docker(code2, host_ws, image, timeout_sec=30)
        result_file = ws / "generated" / "rewrite_test.txt"
        test("宿主机路径文件写入（路径重写）",
             result_file.exists() and result_file.read_text() == "rewrite_ok",
             out2[:300])

        # 测试 3: 使用相对路径（不应被修改）
        code3 = '''import pandas as pd
df = pd.read_csv("test.csv")
df.to_csv("generated/relative_result.csv", index=False)
print("relative_ok, rows:", len(df))
'''
        out3 = execute_in_docker(code3, host_ws, image, timeout_sec=30)
        rel_file = ws / "generated" / "relative_result.csv"
        test("相对路径读写（不受重写影响）",
             "relative_ok" in out3 and rel_file.exists(),
             out3[:300])

        # 测试 4: matplotlib + 宿主机路径
        code4 = f'''import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.figure()
plt.plot([1,2,3],[4,5,6])
plt.savefig(r"{host_ws}/generated/rewrite_plot.png", dpi=72)
plt.close()
print("png_ok")
'''
        out4 = execute_in_docker(code4, host_ws, image, timeout_sec=30)
        png_file = ws / "generated" / "rewrite_plot.png"
        test("宿主机路径 PNG 写入（路径重写）",
             png_file.exists() and png_file.stat().st_size > 500,
             f"exists={png_file.exists()}, out={out4[:200]}")

    finally:
        shutil.rmtree(ws, ignore_errors=True)

    print(f"\n{'='*60}")
    print(f"路径重写测试结果: {PASSED} 通过, {FAILED} 失败")
    print(f"{'='*60}")
    sys.exit(1 if FAILED > 0 else 0)


if __name__ == "__main__":
    main()
