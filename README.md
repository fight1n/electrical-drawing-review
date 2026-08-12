# 电气图纸自动化审核系统 (Electrical Drawing Review, `edr`)

基于 LLM 的电气图纸自动化审核系统。系统以 **Claude SDK Tool Use** 为核心审核引擎，
围绕「解析 → 规则筛选 → 上下文构建 → 并行审核 → 报告生成」五节点轻量状态机编排，
覆盖**架构设计、检索机制、成本优化 / 多模态解析、标准化交付**四大模块。

> 系统可在**无任何外部依赖、无 API Key、无 GPU 权重**的情况下端到端离线运行
> （内置确定性 Mock 适配器 + 纯 Python 解析 / 报告降级实现），部署者接入真实
> Claude / OpenAI 密钥或本地 MinerU、PP-DocLayout 权重后即自动切换到生产路径。

---

## 1. 核心特性

| 模块 | 关键能力 | 实现位置 |
| --- | --- | --- |
| **架构设计** | 五节点轻量状态机、LLM 抽象层（多模型热切换）、全链路 Trace 审计、`asyncio.gather` 并行审核 + 规则类别条件过滤 | `core/state_machine.py`、`core/llm_adapter.py`、`core/trace.py`、`review/reviewer.py` |
| **检索机制** | 倒排索引精确匹配 + Agent 语义重排两阶段检索；实体识别提取标准编号与参数做精确召回，LLM 二次相关性筛选排序 | `retrieval/` |
| **成本优化** | 系统 Prompt + 全局共享上下文 + 规则专属上下文三段式动态输入裁剪（按四类规则差异化预算）；MinerU + AST 融合解析管道（正则表格保护 + 语义分块三层策略）；PP-DocLayout 版面分割微调挂载点 | `rules/context_builder.py`、`parsing/` |
| **标准化交付** | FreeCAD 底层原子化 Tool 封装；ReportLab 结构化 PDF（违规条款 / 位置截图 / 修改建议）；`StreamingResponse` 流式输出，渲染预算 ≤ 3 秒 | `cad/freecad_tools.py`、`report/pdf_report.py`、`api.py` |

---

## 2. 系统架构

### 2.1 五节点轻量状态机

```
        ┌──────────┐
        │  PARSE   │  解析：MinerU + PP-DocLayout + AST 融合 → ParsedDrawing
        └────┬─────┘
             ▼
       ┌─────────────┐
       │ RULE_SELECT │  检索：倒排索引精确召回 + 实体识别 → 候选标准条款
       │             │         + LLM 语义重排 → 命中的 RuleMatch 列表
       └────┬────────┘
            ▼
      ┌──────────────┐
      │ CONTEXT_BUILD│  三段式动态裁剪：system + 全局共享上下文 + 规则专属上下文
      └────┬─────────┘
           ▼
     ┌────────────────┐
     │ PARALLEL_REVIEW│  asyncio.gather 并行审核；按规则类别条件过滤任务
     └────┬───────────┘
          ▼
       ┌─────────┐
       │ REPORT  │  FreeCAD 截图 + ReportLab/纯Python PDF；StreamingResponse
       └─────────┘
```

每个节点执行前后都会写入 `TraceCollector`，形成「节点耗时 / LLM 调用 / Token 消耗 / 成本 /
命中规则 / 违规项」全链路审计记录，可导出为 JSON 供追溯。

### 2.2 技术栈

- **语言**：Python 3.11+
- **编排**：`asyncio`（原生，无重框架）
- **LLM 抽象**：自研 `LLMAdapter` 统一异步接口；`anthropic` / `openai` 为可选依赖
- **HTTP**：FastAPI + Uvicorn（`StreamingResponse` 流式输出）
- **报告**：ReportLab（含 CJK 中文字体）；环境缺失时自动降级为内置纯 Python PDF 生成器
- **CAD**：FreeCAD（可选）；缺失时降级为 DXF / SVG 解析
- **解析**：MinerU（可选服务）、PP-DocLayout（微调权重可选）、内置 AST / 正则解析兜底
- **测试**：pytest

---

## 3. 工程目录结构

```
electrical-drawing-review/
├── config/default.yaml            # 全局配置（可被环境变量覆盖）
├── pyproject.toml                 # 打包与 pytest 配置
├── requirements.txt               # 核心依赖（离线可运行）
├── requirements-llm.txt           # 真实 LLM/解析依赖（Claude/OpenAI/MinerU…）
├── .env.example                   # 环境变量模板
├── Dockerfile                     # 容器化部署
├── README.md                      # 本文件
├── src/edr/
│   ├── __init__.py
│   ├── cli.py                     # 命令行入口（demo / review）
│   ├── api.py                     # FastAPI 服务（含流式端点）
│   ├── wiring.py                  # 依赖装配：build_pipeline()
│   ├── core/
│   │   ├── config.py              # 配置加载（yaml + env）
│   │   ├── models.py              # 数据模型（DrawingElement/BBox/Entity/…）
│   │   ├── trace.py               # 全链路 Trace 审计
│   │   ├── llm_adapter.py         # LLM 抽象层 + Mock/Claude/OpenAI + 路由器
│   │   └── state_machine.py       # 五节点状态机 + PipelineContext
│   ├── parsing/
│   │   ├── doclayout.py           # PP-DocLayout 版面分割（微调挂载 + 启发式兜底）
│   │   ├── mineru_adapter.py      # MinerU 适配器（服务优先 + 本地兜底）
│   │   ├── ast_parser.py          # AST 结构化图元解析 + 实体抽取
│   │   ├── semantic_chunk.py      # 正则表格保护 + 语义分块（三层策略）
│   │   └── pipeline.py            # 融合解析管道
│   ├── retrieval/
│   │   ├── inverted_index.py      # 倒排索引精确匹配
│   │   ├── entity_recognizer.py   # 实体识别（标准编号 / 参数）
│   │   ├── reranker.py            # LLM 语义重排（第二阶段）
│   │   └── engine.py              # 两阶段检索编排
│   ├── rules/
│   │   ├── rule_categories.py     # 四类规则定义
│   │   ├── registry.py            # 规则注册表
│   │   └── context_builder.py     # 三段式动态上下文裁剪
│   ├── review/
│   │   └── reviewer.py            # 并行审核（asyncio.gather + 类别过滤）
│   ├── cad/
│   │   └── freecad_tools.py       # FreeCAD 原子化 Tool（含 DXF/SVG 兜底）
│   ├── report/
│   │   ├── pdf_report.py          # ReportLab 报告生成（CJK + 降级）
│   │   └── mini_pdf.py            # 纯 Python PDF 降级生成器
│   └── standards/sample/          # 示例标准语料库（GB 50054 / GB/T 4728）
├── examples/
│   ├── sample_drawing.py          # 内置示例图纸（结构化 dict）
│   └── demo.py                    # 端到端离线演示
├── tests/                         # pytest 用例
└── outputs/                       # 运行产物（报告 / trace / 截图）
```

---

## 4. 快速开始

### 4.1 安装

```bash
# 克隆（部署到自己的仓库后）
git clone <your-fork-url> electrical-drawing-review
cd electrical-drawing-review

# 创建虚拟环境（推荐）
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 核心依赖（足以离线运行 demo / CLI / 测试）
pip install -r requirements.txt

# 如需接入真实模型与解析服务，再装：
pip install -r requirements-llm.txt
```

### 4.2 零配置离线演示

```bash
# 方式 A：直接运行 demo 脚本
PYTHONPATH=src python examples/demo.py

# 方式 B：通过 CLI
PYTHONPATH=src python -m edr.cli demo --out outputs
```

输出：在 `outputs/` 生成结构化 JSON 报告与 PDF 报告，并打印命中规则 / 违规项 /
成本统计。

### 4.3 运行测试

```bash
PYTHONPATH=src python -m pytest -q
```

---

## 5. 配置

配置来自 `config/default.yaml`，可被环境变量覆盖（见 `.env.example`）。关键项：

```yaml
llm:
  provider: mock          # mock | claude | openai —— 默认 mock 离线可跑
  claude_model: claude-sonnet-4-20250514
  openai_model: gpt-4o
  temperature: 0.0
  max_tokens: 2048

runtime:
  max_concurrency: 8      # asyncio.gather 并行上限
  enable_rerank: true     # 是否启用 LLM 语义重排（第二阶段）
  doclayout_weights: ""   # 微调后的 PP-DocLayout 权重路径（空=启发式兜底）
  mineru_endpoint: ""     # MinerU 服务地址（空=本地 AST 解析兜底）
  trace_dir: outputs/trace

rules:
  categories:             # 四类规则，各自差异化上下文预算（token）
    geometry_size:       { context_budget: 1200, requires: [bbox, dims] }
    symbol_annotation:   { context_budget: 1000, requires: [symbols, annotations] }
    parameter_threshold: { context_budget: 1400, requires: [params, ratings] }
    wiring_topology:     { context_budget: 1600, requires: [nets, connections] }

standards:
  corpus_dir: src/edr/standards/sample
  build_index: true       # 启动时构建倒排索引

report:
  title: 电气图纸自动化审核报告
  target_seconds: 3.0
  include_screenshots: true
```

### 接入真实模型

复制 `.env.example` 为 `.env` 并填写：

```ini
EDR_LLM_PROVIDER=claude
ANTHROPIC_API_KEY=sk-ant-xxxx
# 或
EDR_LLM_PROVIDER=openai
OPENAI_API_KEY=sk-xxxx
```

`provider` 也可在运行时热切换（见 `core/llm_adapter.py` 的 `LLMAdapterRouter`）。

---

## 6. 模块详解

### 6.1 架构设计：状态机 + LLM 抽象层 + 并行审核

- **五节点状态机**（`core/state_machine.py`）：`PARSE → RULE_SELECT → CONTEXT_BUILD →
  PARALLEL_REVIEW → REPORT`，状态转移表驱动，支持节点钩子（`on_progress`）与可追溯的
  `PipelineContext`。
- **LLM 抽象层**（`core/llm_adapter.py`）：统一异步 `complete()` 接口；`MockLLMAdapter`
  （离线确定性，含模拟 Tool-Use 循环）、`ClaudeLLMAdapter`（基于 Claude SDK Tool Use）、
  `OpenAILLMAdapter`；`LLMAdapterRouter` 支持运行时热切换模型，任意调用自动写入 Trace。
- **并行审核**（`review/reviewer.py`）：`asyncio.gather` 并发执行各规则审核协程；
  **规则类别条件过滤**——仅当图纸解析结果包含该类别所需字段（如 `geometry_size` 需要
  bbox/尺寸、`wiring_topology` 需要 nets）时才派发审核任务，避免无效 LLM 调用。

### 6.2 检索机制：两阶段（精确召回 + 语义重排）

1. **第一阶段 · 倒排索引精确匹配**（`retrieval/inverted_index.py`）：对标准语料分词建
   倒排索引；`entity_recognizer.py` 抽取图纸中的**标准编号**（如 `GB 50054`、`GB/T 4728`）
   与**关键参数**（截面积、电气间隙、额定电流等），做精确召回。
2. **第二阶段 · Agent 语义重排**（`retrieval/reranker.py`）：将候选条款与图纸上下文送入
   LLM 做相关性二次判别与排序；无 LLM 时退化为基于关键词重合度的启发式评分，保证离线可跑。

### 6.3 成本优化：三段式动态输入裁剪 + 多模态解析

- **三段式上下文**（`rules/context_builder.py`）：每条规则的输入由
  `系统 Prompt（全局固定）` + `全局共享上下文（图纸级提炼）` + `规则专属上下文（该条款 +
  相关图元，预算受类别约束）` 三段拼接；按四类规则差异化 `context_budget`，从源头压低 Token。
- **MinerU + AST 融合解析**（`parsing/`）：优先调用 MinerU 服务抽取版式与文本；PP-DocLayout
  提供版面分割（支持挂载微调权重）；AST 结构化解析负责图元 / 实体抽取。三层策略：
  **正则表格保护**（保留标准条款表格不被切碎）→ **版面分块** → **语义分块**，输出结构化
  `ParsedDrawing`。任一重型组件缺失时自动降级为内置 AST / 正则解析。

### 6.4 标准化交付：FreeCAD 原子 Tool + 结构化 PDF + 流式输出

- **FreeCAD 原子化 Tool**（`cad/freecad_tools.py`）：封装图元解析、实体标注、参数提取等
  底层原子操作；检测到 FreeCAD 不可用时降级读取 DXF / SVG 文本以获取图元与坐标。
- **结构化 PDF**（`report/pdf_report.py`）：基于 ReportLab 生成含**违规条款、位置截图、
  修改建议**的报告，内置 CJK 中文字体；ReportLab 缺失时降级为内置纯 Python PDF 生成器
  （`report/mini_pdf.py`），保证任意环境都能产出可读 PDF。
- **流式输出**（`api.py`）：`POST /review/stream` 以 NDJSON 流式返回各节点进度，最终
  `pdf` 事件携带报告与 base64 PDF；`POST /review/pdf` 直接以 `StreamingResponse` 流式
  下发 PDF。渲染预算 ≤ 3 秒（见 `report.target_seconds`）。

---

## 7. HTTP API

启动服务（需安装 FastAPI / Uvicorn）：

```bash
pip install -r requirements-llm.txt
PYTHONPATH=src uvicorn edr.api:app --host 0.0.0.0 --port 8000
```

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/health` | GET | 存活检查 + 当前 provider |
| `/review` | POST | 返回 JSON 报告 + base64 PDF + trace |
| `/review/pdf` | POST | `StreamingResponse` 流式返回 PDF 文件 |
| `/review/stream` | POST | NDJSON 流式返回节点进度，末尾 `pdf` 事件携带报告 |

请求体示例：

```json
{
  "drawing_id": "SAMPLE-001",
  "drawing": {
    "drawing_id": "SAMPLE-001",
    "raw_text": "QF1 断路器 ...",
    "elements": [ { "id": "E1", "type": "symbol", "symbol": "QF1", ... } ],
    "entities": [ { "kind": "standard_code", "value": "GB50054" } ]
  }
}
```

也可直接传图纸文件路径字符串由解析管道读取。

---

## 8. 部署

### 8.1 Docker

```bash
docker build -t electrical-drawing-review .
docker run -p 8000:8000 \
  -e EDR_LLM_PROVIDER=claude \
  -e ANTHROPIC_API_KEY=sk-ant-xxxx \
  electrical-drawing-review
```

### 8.2 自行部署到 GitHub 供他人使用

1. Fork / 克隆本仓库到自己的 GitHub 账号。
2. 在仓库 **Settings → Secrets** 中配置 `ANTHROPIC_API_KEY`（或 `OPENAI_API_KEY`）。
3. 如需 CI 自动测试，可在 `.github/workflows/` 添加 pytest 工作流（仓库已含 `requirements.txt`
   与 `pyproject.toml` 的 pytest 配置）。
4. 使用者 `git clone` 后按第 4 节即可一键运行；不填密钥默认走 Mock 离线模式。

---

## 9. 扩展指南

- **新增审核规则**：在 `rules/registry.py` 的 `default_registry()` 中追加 `Rule` 实例，
  指定 `category`（四类之一）、`clause_ref`、`clause_text`、`description`；可选补充标准语料
  到 `standards/` 让其被检索命中。
- **扩充标准库**：向 `standards/` 添加 `.md` 条款文件（建议按「标准号 + 条款编号」分段），
  启动时会自动构建倒排索引。
- **切换 / 新增模型**：实现 `core/llm_adapter.py` 中的 `BaseLLMAdapter` 子类，注册到
  `LLMAdapterRouter`，并在 `config`/`env` 中切换 `provider`。
- **接入真实解析**：配置 `runtime.mineru_endpoint` 指向 MinerU 服务，或放置微调后的
  PP-DocLayout 权重路径到 `runtime.doclayout_weights`。

---

## 10. 测试、降级与限制

- **测试**：`pytest` 覆盖倒排索引、上下文裁剪、解析管道、端到端管线（9 项用例，默认 Mock 模式）。
- **离线降级策略**：
  - 无 API Key → `MockLLMAdapter`（确定性启发式判定，演示用）。
  - 无 ReportLab → `mini_pdf.py` 纯 Python 生成器。
  - 无 MinerU / PP-DocLayout → 内置 AST + 正则解析。
  - 无 FreeCAD → 读取 DXF / SVG 文本获取图元。
- **已知限制 / 后续路线**：
  - Mock 判定为规则化启发式，仅用于离线演示与流程验证；生产审核须接入真实 LLM。
  - 示例标准语料为条款摘录，生产环境需替换为完整带版权的标准文本并做合规审查。
  - 位置截图当前为占位，接入 CAD 渲染器后可自动填充真实裁剪图。

---

## 11. 许可证

本项目为示例实现，遵循仓库所属 LICENSE（未声明时默认按 Apache-2.0 处理）。标准条款文本
版权归原发布机构所有，请勿随代码分发受版权保护的全文。
