
1. **左侧一直 Loading 的原因**  
   侧栏的数据完全来自后台 `/workspace/files` 与 `/workspace/tree` 接口，代码在 [ThreePanelInterface](cci:1://file:///d:/Python-Learning/deepanalyze/demo/chat/components/three-panel-interface.tsx:115:0-3280:1) 的 [loadWorkspaceFiles](cci:1://file:///d:/Python-Learning/deepanalyze/demo/chat/components/three-panel-interface.tsx:542:2-555:4) / [loadWorkspaceTree](cci:1://file:///d:/Python-Learning/deepanalyze/demo/chat/components/three-panel-interface.tsx:557:2-596:4) 里通过 `session_id` 去拉取文件树并在成功后才渲染内容 @demo/chat/components/three-panel-interface.tsx#503-610。若 API server 未连上、`session_id` 为空、或接口返回 4xx/5xx，就会始终显示 Loading。排查建议：  
   - 确认 WebUI 设置里填入 `http://localhost:8200/v1`，保存后刷新。  
   - 在浏览器控制台看网络请求 `/workspace/*` 是否成功（200），否则按日志修复 API。  
   - 若你切换浏览器/清空缓存，Session ID 会重置，需要重新开始一次对话。  

2. **页面基本用法**  
   - **顶部设置**：在“Settings”里填 API Base (`http://localhost:8200/v1`)、可随便填 API Key（只做前端校验）。底层请求会按 `API_CONFIG` 中的 `BACKEND_BASE_URL/FILE_SERVER_BASE` 调用 FastAPI 与文件服务 @demo/chat/lib/config.ts#1-67。  
   - **左列（Workspace）**：上传文件、浏览/下载/删除/新建目录，对应的按钮都会把当前 `session_id` 参数带到 `/workspace/*` 接口 @demo/chat/components/three-panel-interface.tsx#541-670。  
   - **中列（聊天）**：输入需求 → 点击发送，前端会把历史消息与附件打包成 `POST /chat/completions` 请求（默认模型 `deepanalyze-8b`，可改代码或在 API 端映射）@demo/chat/components/three-panel-interface.tsx#2132-2159。  
   - **右列（结果 & 代码执行）**：  
     1. “Export Report” 调 `POST /export/report` 生成 Markdown/PDF 并刷新文件树 @demo/chat/components/three-panel-interface.tsx#248-274。  
     2. “Execute Code” 把编辑器内容发到 `/execute`，用于运行分析脚本 @demo/chat/components/three-panel-interface.tsx#1338-1349。  
     3. Workspace 区域可以预览/下载模型生成的所有文件。  

若左侧仍 Loading，先确认上述请求是否成功，再把控制台/接口错误贴出来，我们可以继续定位。

