# SoftArena ALE Rollout Platform PRD

## 1. 背景与目标

`toolize` 已经把 1000+ 软件包适配成可被 Agent 调用的工具集合，包含 `baseline/*/*/config.toml` 中的工具 schema、执行参数、timeout、工作手册，以及 `bin2mcp/*` 中的 MCP 服务实现。项目目标是在这些工具之上构建一套可扩展的 ALE 刷榜平台：

- 快速接入多个工具型环境，覆盖数据库、开发工具、文本处理、系统运维、科学计算等类别。
- 批量 rollout 模型轨迹，产出可训练、可审计、可复现的数据。
- 建立从环境定义、任务采样、执行沙箱、verifier、数据湖、训练、评测到 ALE 提交的闭环。
- 支持模型版本迭代，通过多环境自评稳定衡量能力变化，并与 ALE 官方/榜单评估对齐。

## 2. 非目标

- 不重写 `toolize` 现有工具适配层。
- 不把每个软件包都强行做成独立环境；优先做高价值、多任务、可验证的组合环境。
- 不依赖人工主观打分作为主 verifier；人工标注只用于任务设计、失败分析和 verifier 校准。
- 不在第一阶段追求复杂 GUI 环境，先以 CLI/JSON-RPC/MCP 工具为主。

## 3. 核心用户与使用场景

### 3.1 平台开发者

- 接入新的环境族，比如 SQLite、Git/build、文本转换、网络诊断。
- 为环境编写任务模板、初始化器和 verifier。
- 查看环境健康度、rollout 成功率、失败样例和回归报告。

### 3.2 训练工程师

- 批量生成 SFT / RL / preference 数据。
- 根据任务难度、工具类别、失败类型过滤数据。
- 复现指定轨迹，定位模型或环境问题。

### 3.3 评测与打榜负责人

- 对多个候选模型运行统一 eval suite。
- 生成模型能力雷达图、回归差异、ALE 格式提交包。
- 校验本地评测与 ALE 官方环境的一致性。

## 4. 总体架构

```text
                 +--------------------+
                 |  Model Registry    |
                 |  base / sft / rl   |
                 +----------+---------+
                            |
                            v
+-------------+    +--------+---------+    +----------------+
| Env Registry| -> | Rollout Orchestr. | -> | Trajectory Lake |
| tasks/specs |    | workers/scheduler |    | jsonl/parquet   |
+------+------+    +--------+---------+    +--------+-------+
       |                    |                       |
       v                    v                       v
+------+------+    +--------+---------+    +--------+-------+
| Tool Registry|   | Runtime Sandbox  |    | Training Pipe   |
| toolize MCP  |   | docker/uds/fs    |    | sft/rl/dpo      |
+------+------+    +--------+---------+    +--------+-------+
       |                    |                       |
       v                    v                       v
+------+------+    +--------+---------+    +--------+-------+
| Tool Servers |   | Verifier Runner  |    | Eval & ALE Pack |
| 1000+ tools  |   | oracle/scoring   |    | local/official  |
+-------------+    +------------------+    +----------------+
```

### 4.1 分层职责

- `tool registry`：索引 `toolize` 工具，提供 tool name、schema、镜像/命令、类别、健康状态和成本信息。
- `env registry`：管理环境定义、任务模板、允许工具集合、初始状态、verifier、难度标签。
- `runtime sandbox`：为每个 episode 创建隔离 workspace、启动工具服务、挂载输入数据、限制网络/时间/资源。
- `rollout orchestrator`：调度模型与环境交互，记录 observation/action/result/verifier_trace。
- `trajectory lake`：存储原始轨迹、压缩轨迹、评分结果、环境版本、模型版本、失败原因。
- `training pipeline`：把轨迹转成 SFT/RL/preference 数据，训练并注册模型版本。
- `eval pipeline`：在固定任务集上跑模型，自评能力变化，并生成 ALE 评估提交产物。

## 5. 代码与目录设计

建议在仓库根目录新增平台代码，不侵入 `toolize`：

```text
softarena/
  registry/
    tools.py              # 从 toolize config.toml / MCP tools/list 构建工具索引
    envs.py               # 环境注册与加载
    schemas.py            # Pydantic/dataclass schema
  runtime/
    sandbox.py            # episode workspace、容器、资源限制
    mcp_client.py         # JSON-RPC/MCP 调用统一客户端
    artifact_store.py     # episode 文件、日志、stdout/stderr
  envs/
    sqlite/
      env.yaml
      tasks.yaml
      init.py
      verifier.py
    build_debug/
      env.yaml
      tasks.yaml
      init.py
      verifier.py
  rollout/
    runner.py             # 单 episode loop
    scheduler.py          # 批量任务调度
    policies.py           # model adapter / sampling params
    trace.py              # 轨迹 schema
  training/
    datasets.py           # trajectory -> train samples
    sft.py
    preference.py
    rl.py
  eval/
    suites.yaml
    evaluator.py
    report.py
    ale_pack.py
  cli.py
docs/
  SOFTARENA_ALE_ROLLOUT_PRD.md
toolize/
  baseline/
  bin2mcp/
```

## 6. Infra 设计

### 6.1 Tool Registry

输入来源：

- `toolize/baseline/*/*/config.toml`：优先读取工具 schema、描述、参数和 timeout。
- `toolize/bin2mcp/*-mcp`：补充 MCP 服务目录、README、测试和示例输出。
- `toolize/baseline/reports/*.json`：补充构建成功率、健康状态、跳过原因。
- 运行时 `tools/list`：校验真实可调用工具与静态配置一致。

核心字段：

```yaml
tool_id: cli-db/sqlite3/sqlite_query
package: sqlite3
category: cli-db
server: mass-toolize/sqlite3
transport: stdio_jsonrpc
schema:
  input: {...}
timeout_secs: 300
side_effect: read_only
health:
  build: pass
  smoke: pass
  last_checked_at: ...
tags: [database, query, json-output]
```

设计要点：

- 工具 schema 原样继承，环境只声明 allowlist，避免重复维护。
- 给工具补充 `side_effect`、`cost`、`determinism`、`requires_network`、`requires_gui` 标签，方便任务采样和安全限制。
- registry 生成不可变版本号，例如 `tool_registry_sha`，写入每条轨迹。

### 6.2 Env Registry

环境是任务分布，而不是工具本身。一个环境可以使用一个或多个工具包。

```yaml
env_id: sqlite.data_repair.v1
name: SQLite Data Repair
version: 1
tool_allowlist:
  - cli-db/sqlite3/sqlite_exec
  - cli-db/sqlite3/sqlite_query
  - cli-db/sqlite3/sqlite_schema
  - cli-db/sqlite3/sqlite_import
  - cli-db/sqlite3/sqlite_export
entrypoint:
  init: envs.sqlite.init:create_episode
  verifier: envs.sqlite.verifier:verify
episode:
  max_steps: 20
  timeout_secs: 600
  workspace_policy: isolated_tmp
scoring:
  type: deterministic
  max_score: 1.0
tags: [database, structured-data, deterministic]
```

### 6.3 Episode 生命周期

1. `sample_task(seed, difficulty)` 生成任务实例。
2. 创建隔离 workspace，写入输入文件、数据库、README 或测试工程。
3. 启动工具服务或容器，暴露 MCP tools。
4. 给模型发送 system/developer/task prompt 和可用工具 schema。
5. 模型循环执行 `tool_call -> observation`，直到 `final_answer` 或 step limit。
6. verifier 读取 workspace 和日志，输出 score、pass/fail、diagnostics。
7. 轨迹、artifact、评分结果落盘。

### 6.4 Trajectory Schema

每条 episode 保存完整可复现信息：

```json
{
  "episode_id": "...",
  "env_id": "sqlite.data_repair.v1",
  "env_version": "1",
  "task_id": "...",
  "seed": 123,
  "difficulty": "medium",
  "model": {
    "name": "evolve-sft-001",
    "checkpoint": "...",
    "sampling": {"temperature": 0.2}
  },
  "tool_registry_sha": "...",
  "prompt": {...},
  "steps": [
    {
      "index": 0,
      "message": "...",
      "tool_call": {"name": "sqlite_query", "arguments": {...}},
      "observation": {"ok": true, "content": "..."},
      "latency_ms": 120
    }
  ],
  "final_answer": "...",
  "verifier": {
    "score": 1.0,
    "passed": true,
    "checks": [...],
    "diagnostics": "..."
  },
  "artifacts": {
    "workspace_ref": "...",
    "logs_ref": "..."
  }
}
```

## 7. 环境定义与轻量接入

### 7.1 环境最小接口

每个环境只需要实现三类文件：

```text
env.yaml      # 元数据、工具 allowlist、资源限制、评分类型
tasks.yaml    # 任务模板、难度、采样参数、公开/隐藏测试说明
verifier.py   # verify(context) -> VerificationResult
```

如果任务需要生成文件或初始状态，再加：

```text
init.py       # create_episode(seed, task_spec) -> EpisodeSpec
```

### 7.2 Verifier 类型

- `state verifier`：检查最终文件、数据库、配置、目录结构是否符合预期。
- `unit test verifier`：运行隐藏测试，适合代码修复、构建、CLI 行为。
- `semantic verifier`：解析输出并比较语义等价，例如 SQL 查询结果、JSON schema、图像元数据。
- `tool trace verifier`：检查是否使用了指定工具、避免禁用工具或危险命令。
- `composite verifier`：多个 check 加权，支持 partial credit。

建议返回结构：

```python
class VerificationResult:
    score: float
    passed: bool
    checks: list[CheckResult]
    diagnostics: str
    metrics: dict[str, float | int | str]
```

### 7.3 首批环境建议

优先选 deterministic、可自动验证、任务可参数化的环境：

| 环境 | 工具来源 | 任务例子 | Verifier |
| --- | --- | --- | --- |
| `sqlite.data_repair` | `cli-db/sqlite3` | 导入脏 CSV、修复 schema、写查询导出报表 | SQL 结果 + schema check |
| `build.fix_compile` | `bear/clang/gcc/make` | 修复小 C/C++ 项目编译失败 | hidden tests + compile_commands |
| `text.transform` | `sed/awk/jq/yq/iconv` | 多格式文本清洗、JSON/CSV 转换 | golden file semantic diff |
| `archive.forensics` | `tar/gzip/file/sha*` | 解包、识别文件、恢复目标数据 | 文件 hash + metadata |
| `net.dns_debug` | `dig/curl/openssl` | 诊断 DNS/TLS/HTTP 问题 | mocked network + expected report |
| `docs.convert` | `pandoc/libreoffice/pdf` | 文档转换、抽取表格、生成摘要 | text extraction + layout smoke |

### 7.4 任务模板

```yaml
task_id: sqlite_repair_missing_indexes
difficulty: medium
prompt_template: |
  You are given a SQLite database at {db_path}. Create the required indexes
  and produce a JSON report at {report_path}.
inputs:
  db_seed: random
  rows: [1000, 5000]
hidden_expectations:
  required_indexes:
    - idx_orders_customer_id
  query_latency_ms_lt: 100
```

任务设计原则：

- 公开目标明确，隐藏测试检验泛化。
- 输入可 seed 化，避免训练集过拟合固定答案。
- 允许多路径解法，只验证最终状态和关键约束。
- 每个环境至少有 smoke/dev/eval 三套 split。

## 8. Rollout 到训练 Pipeline

### 8.1 数据分层

- `raw_trajectory`：完整消息、工具调用、observation、artifact。
- `verified_episode`：加 verifier 分数、错误分类、环境元数据。
- `train_sample`：面向训练的消息格式，过滤敏感日志和无效片段。
- `preference_pair`：同任务多轨迹之间按 verifier 分数构造 chosen/rejected。
- `rl_episode`：保留 step-level reward 和 terminal reward。

### 8.2 Rollout 策略

- `exploration rollout`：较高 temperature，多样化搜索。
- `eval rollout`：固定 temperature/seed，保证可比。
- `repair rollout`：对失败轨迹追加诊断 prompt，再尝试一次。
- `teacher rollout`：强模型生成高质量 seed 数据。
- `student rollout`：当前模型自产数据，用 verifier 做筛选。

### 8.3 数据过滤

保留：

- verifier pass 或高 partial score。
- 失败但诊断价值高的轨迹，用于 preference/rejection。
- 使用工具过程合理、没有明显无效循环的轨迹。

剔除：

- 环境或工具调用失败导致的 false negative。
- verifier 不稳定、重跑分数不一致的 episode。
- 泄漏 hidden answer 的任务。
- 只靠最终文本猜答案、没有实际修改状态的轨迹。

### 8.4 训练闭环

```text
v0 model
  -> rollout train/dev tasks
  -> verifier scoring
  -> dataset build
  -> SFT warm start
  -> preference/RL on verified tasks
  -> register v1
  -> eval suite
  -> failure mining
  -> add tasks/verifiers
  -> next iteration
```

建议阶段：

- Phase A：SFT，用高分轨迹教会工具调用格式和环境策略。
- Phase B：DPO/IPO，用同任务 pass/fail 或高低分轨迹做偏好优化。
- Phase C：RL，terminal reward 由 verifier score 给出，step penalty 控制工具滥用。
- Phase D：curriculum，根据模型在各环境 pass rate 自动提高任务难度。

## 9. 评测与 ALE 打榜

### 9.1 本地自评

固定评测集：

- `smoke`：每个环境 5-20 条，验证平台和工具可用。
- `dev`：每个环境 100-500 条，用于日常迭代。
- `heldout`：严格冻结，不进入训练。
- `stress`：长上下文、多工具、多步骤、资源紧张任务。

指标：

- `pass@1`、`pass@k`。
- 平均 verifier score。
- 平均 step 数、工具调用成功率、超时率。
- 按环境、工具类别、难度、错误类型分桶。
- 回归指标：新模型相对上一版本的 win/loss/tie。

报告输出：

```text
reports/
  eval_2026-06-24_model-v3/
    summary.json
    by_env.csv
    regressions.jsonl
    failures/
    leaderboard.md
```

### 9.2 ALE 对齐

需要实现 `eval/ale_pack.py`：

- 把本地 env/task 映射到 ALE 要求的任务格式。
- 固定模型调用参数和工具暴露方式。
- 导出官方评估需要的 trajectories、answers、metadata。
- 运行提交前校验：无训练 split 泄漏、环境版本固定、随机种子记录完整。

打榜策略：

- 本地 `heldout` 与 ALE public/dev 分开维护。
- 每次提交前跑完整 regression suite，确保不是只优化某一类环境。
- 保留 `submission_manifest.json`，记录模型 checkpoint、tool registry sha、env suite sha、代码 commit。

### 9.3 防止评测污染

- `eval` split 不参与训练数据构建。
- 任务模板可公开，实例 seed/hidden expectation 对训练不可见。
- verifier 只能输出诊断，不输出 hidden target。
- eval worker 使用只读环境包和独立 artifact store。

## 10. 里程碑

### M0：项目骨架与规范

- 建立 `softarena` 基础目录。
- 定义 `ToolSpec`、`EnvSpec`、`EpisodeSpec`、`Trajectory`、`VerificationResult` schema。
- 实现静态 tool registry 扫描。
- 写 1 个 fake env 做端到端 smoke。

验收：

- `softarena list-tools` 能列出工具。
- `softarena list-envs` 能列出环境。
- `softarena run --env fake --model mock` 产出轨迹 JSONL。

### M1：首批可训练环境

- 接入 `sqlite.data_repair`、`text.transform`、`archive.forensics`。
- 每个环境 50+ train、20+ dev、20+ heldout seed。
- verifier 支持 deterministic 重跑。

验收：

- mock/基线模型可批量 rollout。
- 轨迹可复现，verifier 重跑一致率 > 99%。

### M2：数据与训练闭环

- 实现 trajectory lake。
- 实现 SFT dataset builder。
- 实现 preference pair builder。
- 接入训练脚本或外部训练平台。

验收：

- 一次 rollout 可以自动生成 train dataset。
- 模型版本注册后可被 eval pipeline 调用。

### M3：多环境评测与回归分析

- 接入 6+ 环境族。
- 实现 eval suite、报告、失败聚类。
- 支持模型 A/B 对比。

验收：

- 输出按环境/难度/工具类别拆分的评测报告。
- 能列出新模型主要提升和主要退化任务。

### M4：ALE 打榜适配

- 实现 ALE 任务格式导入/导出。
- 实现 submission manifest。
- 对齐官方评测流程。

验收：

- 本地可生成 ALE 提交包。
- 每个提交包可追溯模型、环境、工具和代码版本。

## 11. 风险与对策

| 风险 | 影响 | 对策 |
| --- | --- | --- |
| 工具适配质量不一 | rollout false negative | registry 记录 health，低健康工具不进 eval |
| verifier 过窄 | 模型学会投机 | 多 seed、隐藏测试、semantic check、trace check |
| 轨迹成本过高 | 训练迭代慢 | 分层 rollout、缓存工具镜像、失败早停 |
| eval 污染 | 榜单分数虚高 | split 隔离、manifest、数据构建审计 |
| 多工具环境不稳定 | 分数波动 | deterministic sandbox、资源限制、重跑校验 |
| 只优化简单工具调用 | 泛化差 | curriculum、多步骤任务、跨工具组合 |

## 12. MVP 决策

第一版建议聚焦三件事：

1. 用 `sqlite.data_repair` 跑通环境定义、rollout、verifier、trajectory。
2. 用 `text.transform` 验证多文件输入输出和 semantic diff。
3. 用 `archive.forensics` 验证文件系统状态类任务。

这三个环境覆盖数据库状态、文本转换、文件系统 artifact 三种 verifier 形态，足够打通平台主链路，并能快速产生可训练数据。

## 13. Open Questions

- ALE 官方评估接口最终要求是容器提交、轨迹提交还是远程 API 调用？
- 训练平台采用本地脚本、verl/trl，还是已有内部训练系统？
- 模型工具调用格式是否固定为 MCP/OpenAI tool call，还是需要兼容多种 agent runtime？
- 是否允许环境访问网络？如果允许，需要哪些可控 mock 服务？
- 是否需要把 GUI 工具纳入第一阶段，还是放到 M5 之后？

