# Teach_model 项目优化需求清单

> 生成时间：2026-09-20 ｜ 基于对当前代码库的完整分析
> 优先级说明：P0 = 安全/正确性，必须处理；P1 = 体验/功能，建议尽快；P2 = 工程质量，持续改进
> **进度（2026-09-20）**：P0-2/3/4 与 P1-6/7/8 已完成 ✅；P0-1（API Key）暂缓；P1-9~11 与全部 P2 待办。执行日志见飞书文档。

---

## P0 — 安全与正确性（必须处理）

### 1. API Key 泄露处置 ⚠️ 暂缓（用户要求）
- `deepseek_api.py` 硬编码完整 API Key
- 根目录明文密钥文件 `apikey`，且 `.env` / `apikey` / `deepseek_api.py` 均已被 git 跟踪提交
- 待办：作废旧 Key → `git rm --cached .env apikey`（`.gitignore` 已配置）→ 若仓库推送过远端需清理历史

### 2. 清理坏死的 venv/ 目录
- 现 `venv/` 从其他项目（Tech_llm）拷贝而来，python 软链指向不存在的 conda env `AI_ENV`，约 2780 个死文件
- 环境已统一为 conda `teach_llm`，此目录无任何作用
- 待办：确认后执行 `trash venv/` 或 `rm -rf venv/`

### 3. git 跟踪了不应跟踪的文件
- `backend/__pycache__/*.pyc`、`.env`、`apikey` 均在 git 索引中（`.gitignore` 是后加的，对已跟踪文件无效）
- 待办：`git rm -r --cached backend/__pycache__ .env apikey` 后提交

### 4. 替换已弃用的 FastAPI 生命周期钩子
- `main.py` 使用 `@app.on_event("startup")`，在 fastapi 0.141 已弃用（启动时有 DeprecationWarning）
- 待办：改用 `asynccontextmanager` + `FastAPI(lifespan=...)`

### 5. 上传文件缺少大小与内容安全校验
- `/api/upload` 与 chat 内嵌 CSV 均无大小上限，超大文件会耗尽内存
- 待办：限制如 10MB；解析失败时给用户可读错误

---

## P1 — 体验与功能（建议尽快）

### 6. LLM 流式输出到前端
- 现状：后端对 DeepSeek 用了流式，但对前端是等全量结果拼完才返回，长回复要干等 10-30 秒
- 待办：`/api/chat` 改为 SSE（`text/event-stream`），先推 thought 再逐段推 reply，前端渐进渲染

### 7. 前端接入会话管理
- 后端已有 `GET /api/sessions`、`DELETE /api/sessions/{id}`，前端完全未使用
- 待办：侧边栏会话列表（新建/切换/删除/重命名），重启后自动恢复历史

### 8. 理顺 CSV 上传数据流（当前重复设计）
- 现状：`/api/upload` 解析完 DataFrame 直接丢弃，前端再把整个 CSV 文本塞进 chat 请求体重传一遍
- 待办：upload 后服务端暂存（内存或临时文件）返回 file_id，chat 只传 file_id

### 9. 教学动作继续扩展
- train 增加模型：KNN、SVM、梯度提升；支持超参数传入（如 `n_estimators`、`max_depth`）
- plot 增加图型：箱线图、相关性热力图、混淆矩阵可视化（当前混淆矩阵只有文本表格）
- 增加动作：`describe_column`（单列分析）、`correlation`（相关性分析）

### 10. 会话元信息完善
- 会话无标题（列表只有 id 和时间），待办：首轮对话后自动生成标题
- 对话记录导出（Markdown/JSON）

### 11. 支持一次多步操作
- 现状：每轮只执行一个 action，老师说"检查缺失值并用中位数填充"需要两轮
- 待办：agent 循环（执行一个 action 后把结果回喂 LLM，允许连续执行 2-3 步，设步数上限防失控）

---

## P2 — 工程质量（持续改进）

### 12. 测试体系正规化
- 现状：`test_integration.py` 是 print 式脚本，pytest 可收集的测试为 0（却有 .pytest_cache）
- 待办：迁移为 pytest 用例：actions 各动作、charts 构建器、sessions 持久化、API 契约（httpx TestClient，mock LLM）

### 13. 配置集中管理
- 现状：`os.getenv` 散落在 main.py 各处
- 待办：pydantic-settings 的 `Settings` 类统一管理（含校验：缺 Key 时启动警告而非运行时报错）

### 14. 前端模块化
- `app.js` 1822 行单文件，`style.css` 1961 行
- 待办：拆为 ES modules（api.js / chat.js / chart.js / session.js），不需要构建工具，浏览器原生支持

### 15. 引入 pyproject.toml 与代码规范工具
- 待办：`pyproject.toml`（依赖+元数据）、`ruff`（lint+format）、pre-commit

### 16. 可观测性
- 日志增加 request_id 贯穿一次请求；LLM 调用记录耗时与 token 用量
- 排除敏感信息（用户消息正文）默认不入日志

### 17. 部署便利性
- Dockerfile（基于 conda env 或 python:3.13-slim）+ 一键启动
- 如有远端仓库：GitHub Actions 跑 pytest

### 18. 目录去噪
- `skills/`（272 个文件）、`agent-builder/`、`patent_diagrams/` 与应用运行无关
- 已加入 `.gitignore`；建议移出项目目录或归档到独立仓库

---

## 建议执行顺序

1. 先做 P0 的 2/3/4（成本低、收益直接）：删 venv → git 清理 → lifespan 改造
2. P1 按 6（流式）→ 7（会话 UI）→ 8（上传数据流）推进，这三项对使用体验提升最大
3. P2 在功能稳定后逐步落地，优先 12（测试），它是后续所有重构的安全网
