## WebUI 常见问题与基本操作

### 1. 左侧一直 Loading 的原因

侧栏数据完全来自后台 `/workspace/files` 与 `/workspace/tree` 接口，逻辑位于 [ThreePanelInterface](cci:1://file:///d:/Python-Learning/deepanalyze/demo/chat/components/three-panel-interface.tsx:115:0-3280:1) 的 [loadWorkspaceFiles](cci:1://file:///d:/Python-Learning/deepanalyze/demo/chat/components/three-panel-interface.tsx:542:2-555:4) 与 [loadWorkspaceTree](cci:1://file:///d:/Python-Learning/deepanalyze/demo/chat/components/three-panel-interface.tsx:557:2-596:4) 中 @demo/chat/components/three-panel-interface.tsx#503-610。若 API 未连通、`session_id` 为空或接口返回 4xx/5xx，即会持续显示 Loading。


**最终解决方案：** 只运行 `API/start_server.py` 时并不会暴露 `/workspace/*` 路由，导致左侧一直加载。请在另一个终端启动 `demo/backend.py`（或执行 `bash demo/start.sh`，并在需保留现有 vLLM/API 时设置 `SKIP_CLEANUP=1`），再将 WebUI 设置中的 API Base 指向该后端（默认 `http://localhost:8200/v1`）。启动完成后刷新页面即可成功请求文件树，加载状态会消失。@demo/backend.py#1-879 @demo/start.sh#6-42

###