# DeepSeek 数据处理聊天助手

一个基于 FastAPI + Vanilla JS 的前后端分离示例，提供与 DeepSeek 聊天接口的数据科学助手。支持加载 sklearn 内置数据集与 `.dot` 图数据（占位实现），并通过会话上下文完成数据探索。

## 运行要求
- Python 3.10+
- 前端为纯 HTML/CSS/JS，无需额外构建步骤

## 快速开始
1. 进入仓库根目录并安装依赖：
   ```bash
   pip install -r backend/requirements.txt
   ```
2. 在仓库根目录 `.env` 中写入 DeepSeek API Key 与模型名：
   ```
   DEEPSEEK_API_KEY=your_api_key_here
   DEEPSEEK_MODEL=deepseek-chat
   ```
3. 启动后端（默认 8000 端口）：
   ```bash
   uvicorn backend.main:app --reload
   ```
4. 打开浏览器访问 `http://localhost:8000/` 即可使用前端聊天界面。

## 文件结构
```
backend/
  main.py          # FastAPI 入口，路由 /api/chat 与静态文件挂载
  agent.py         # 会话管理、模型调用、指令解析
  data_loader.py   # sklearn 与 DOT 数据加载
  requirements.txt # Python 依赖
frontend/
  index.html
  style.css
  app.js
```

## 数据集说明
- 支持加载：`iris`, `wine`, `breast_cancer`, `california_housing`（均来自 sklearn）以及一个 `dot` 数据集。
- `dot` 数据集默认读取 `backend/data.dot`。如需使用，请将 `.dot` 文件放在 `backend/` 目录下并命名为 `data.dot`，内容将被解析为边列表 DataFrame。

## 交互提示
- 典型对话开场：向助手问好，助手会主动询问要加载的数据集。
- 示例指令：
  - “加载 Iris 数据集”
  - “显示前5行”
  - “列名有哪些？”
  - “帮我总结一下这个数据集”

## 开发说明
- 会话使用内存中的 `session_id` 字典管理，前端在 `localStorage` 里存储 `session_id`。
- 简单数据请求（前几行、列名、describe）在后端直接用 pandas 计算，复杂问题转发到 DeepSeek。
- 前端通过 `fetch('/api/chat')` 与后端通信，并保持消息气泡布局。
