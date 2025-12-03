## WebUI 常见问题与基本操作

### 1. 左侧一直 Loading 的原因

侧栏数据完全来自后台 `/workspace/files` 与 `/workspace/tree` 接口，逻辑位于 [ThreePanelInterface](cci:1://file:///d:/Python-Learning/deepanalyze/demo/chat/components/three-panel-interface.tsx:115:0-3280:1) 的 [loadWorkspaceFiles](cci:1://file:///d:/Python-Learning/deepanalyze/demo/chat/components/three-panel-interface.tsx:542:2-555:4) 与 [loadWorkspaceTree](cci:1://file:///d:/Python-Learning/deepanalyze/demo/chat/components/three-panel-interface.tsx:557:2-596:4) 中 @demo/chat/components/three-panel-interface.tsx#503-610。若 API 未连通、`session_id` 为空或接口返回 4xx/5xx，即会持续显示 Loading。


**最终解决方案：** 只运行 `API/start_server.py` 时并不会暴露 `/workspace/*` 路由，导致左侧一直加载。请在另一个终端启动 `demo/backend.py`（或执行 `bash demo/start.sh`，并在需保留现有 vLLM/API 时设置 `SKIP_CLEANUP=1`），再将 WebUI 设置中的 API Base 指向该后端（默认 `http://localhost:8200/v1`）。启动完成后刷新页面即可成功请求文件树，加载状态会消失。@demo/backend.py#1-879 @demo/start.sh#6-42

###针对截图中的四个问题，根因与处理方式如下：

1. **student_loan.sqlite 已上传却被提示缺失**  
   WebUI 的聊天会话使用 `session_id` 隔离工作区：[get_session_workspace()](cci:1://file:///d:/Python-Learning/deepanalyze/demo/backend.py:139:0-145:22) 会把每个会话的文件存到 `workspace/<session_id>/` 目录，并且 `/workspace/files`、`/workspace/tree` 只读取该目录内容 @demo/backend.py#133-316。若你在会话 A 上传了 `student_loan.sqlite`，再打开新标签页/刷新导致会话变成 B，新的 `session_id` 下就没有这份文件，于是助手会提示缺失。  
   **处理：**
   - 在 WebUI 左上角确认当前会话 ID，保持同一对话继续分析；若会话变动，请在新会话里重新上传。
   - 或者在 WSL 中直接查看 `workspace/<session_id>/`（如 `ls workspace/ed0c9c9a/`），确保 `.sqlite` 真正在当前会话目录内。

2. **如果没找到文件，后续为什么还能“分析”**  
   当 [collect_file_info()](cci:1://file:///d:/Python-Learning/deepanalyze/demo/backend.py:184:0-199:28) 拿不到 `student_loan.sqlite` 时，助手仍会输出一套通用步骤（加载→清洗→EDA），但这些只是提示，并没有真的执行 SQL 读取或生成结果。实际数据分析只有在代码块被执行并读取到真实文件后才会发生。

3. **反馈里只有代码，没有生成的数据**  
   WebUI 的“Assistant”区域会显示模型产出的 `<Code>` 片段和 `<Execute>` 输出。当前记录中只看到代码说明，说明模型没有真正运行 `sqlite3` 查询（缺少 `<Execute>` 块），因此看不到数据摘要或图表。你可以在“执行代码”编辑器里直接粘贴代码并运行，或等待模型自动触发 `<Code>` 块，确认其输出成功。

4. **“代码生成文件”为空**  
   后端会在执行代码前后对 `workspace/<session_id>/` 做快照，把新增/修改的文件复制到 `workspace/<session_id>/generated` 并通过 `/workspace/files` 隐藏原始副本 @demo/backend.py#644-807。若代码没有写入任何文件（例如未调用 `df.to_csv(...)`），就不会有条目出现。只要在代码里保存图表或报表，比如：
   ```python
   summary = student_loan_df.describe()
   summary.to_csv("student_loan_summary.csv", index=False)
   ```
   执行成功后该 CSV 就会自动出现在“代码生成文件”列表中供下载/预览。

综上：请确认 `student_loan.sqlite` 位于当前会话的 workspace 目录，并在执行分析代码时确保真实运行与文件写出，这样助手才能读到数据并在 UI 中显示结果与生成文件。