# Teach_model · AI 学生教学平台

「AI 扮演学生、你来当老师」的机器学习教学平台。FastAPI + 原生 JS，DeepSeek 驱动，支持多步指令循环、流式输出、真实数据建模与可视化。

> 完整产品文档见飞书「Teach_model 项目文档」文件夹。

## 核心特性

- **多步 Agent 循环**：一条指令自动串联多步操作（如"检查缺失值并训练随机森林"→ check_missing → split → train → evaluate，上限 5 步）
- **9+ 教学动作**：load / preview / check_missing / fill_missing / encode / split / plot / train / evaluate；模型覆盖逻辑回归、线性回归、决策树、随机森林、KNN、SVM、梯度提升树
- **可视化**：直方图、折线、散点、柱状、箱线图、相关性热力图，ECharts 全局自定义主题（含暗色变体）
- **SSE 流式输出**：LLM 增量逐字渲染 + 动作执行状态实时推送
- **会话管理**：SQLite 持久化（重启不丢）、自动生成标题、导出带样式 HTML、按时间分组
- **CSV 上传**：upload_id 引用式数据流，10MB 上限，1 小时缓存
- **工程化**：pydantic-settings 配置中心化、request_id 贯穿日志、单 IP 限流（20 次/分）、LLM 熔断（3 次失败 / 60s）、统一错误格式
- **前端**：品牌渐变主题、暗色模式、微交互动效包、欢迎页引导、响应式抽屉侧栏

## 快速开始

```bash
# 1. 环境（conda 环境 teach_llm，Python 3.13）
conda activate teach_llm
pip install -r backend/requirements.txt

# 2. 配置 .env
DEEPSEEK_API_KEY=your_api_key_here
DEEPSEEK_MODEL=deepseek-chat

# 3. 启动
bash start_server.sh        # 或手动：
# ~/opt/anaconda3/envs/teach_llm/bin/python -m uvicorn backend.main:app --port 8000 --reload

# 4. 访问 http://localhost:8000
```

环境自检：`bash verify_setup.sh`；集成测试：`python test_integration.py`

## 项目结构

```
backend/
  main.py          # FastAPI：路由、SSE、上传、会话/标题/导出 API、限流熔断
  agent.py         # 编排层：多步动作循环、流式、标题生成
  config.py        # pydantic-settings 配置中心
  prompts.py       # 系统提示词与学生水平
  llm_client.py    # DeepSeek 调用与 JSON 解析
  actions.py       # 教学动作执行（含模型注册表）
  charts.py        # ECharts 配置构建
  state.py         # ConversationManager 会话状态
  sessions.py      # SQLite 持久化与空闲清理
  data_loader.py   # sklearn 数据集加载
frontend/          # 原生 JS 单页应用（index.html / app.js / style.css）
```

## API 一览

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/chat` | 非流式对话（兼容） |
| POST | `/api/chat/stream` | SSE 流式对话（status/delta/final 事件） |
| POST | `/api/upload` | 上传 CSV，返回 upload_id |
| GET | `/api/sessions` | 会话列表 |
| GET | `/api/sessions/{id}` | 会话历史详情 |
| DELETE | `/api/sessions/{id}` | 删除会话 |
| POST | `/api/sessions/{id}/generate-title` | LLM 自动生成标题 |
| GET | `/api/sessions/{id}/export?format=html` | 导出对话 HTML |

## 配置项（backend/config.py）

| 环境变量 | 默认 | 说明 |
|----------|------|------|
| `DEEPSEEK_API_KEY` | — | 必填 |
| `DEEPSEEK_MODEL` | deepseek-chat | 模型名 |
| `CORS_ORIGINS` | 本机 8000 | 逗号分隔白名单 |

代码内阈值（上传上限、限流、熔断、清理周期、循环步数）均在 `backend/config.py` 统一调整。
