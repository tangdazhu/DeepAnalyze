"""验证路径重写逻辑。"""

# 模拟 execute_in_docker 中的路径重写
from pathlib import Path

host_ws = "/home/tdz/DeepAnalyze/demo/workspace/session_1770878038604_o97mnomly"

code = '''CSV_PATH = r"/home/tdz/DeepAnalyze/demo/workspace/session_1770878038604_o97mnomly/enrolled.csv"
DB_PATH = r"/home/tdz/DeepAnalyze/demo/workspace/session_1770878038604_o97mnomly/student_loan.sqlite"
OUTPUT_DIR = Path("generated")
'''

print("=== 重写前 ===")
print(code)

# 模拟重写逻辑
variants = {host_ws}
variants.add(host_ws.replace("\\", "/"))
variants.add(host_ws.replace("/", "\\"))

for variant in variants:
    if variant and variant in code:
        code = code.replace(variant, "/data")
        print(f"[路径重写] '{variant}' → '/data'")

print("=== 重写后 ===")
print(code)

# 验证
assert "/home/tdz" not in code, "宿主机路径未被替换!"
assert '/data/enrolled.csv' in code, "CSV 路径替换失败!"
assert '/data/student_loan.sqlite' in code, "DB 路径替换失败!"
assert 'Path("generated")' in code, "相对路径不应被修改!"
print("[PASS] 路径重写验证通过")
