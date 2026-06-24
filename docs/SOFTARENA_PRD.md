# SoftArena PRD

## 1. 项目一句话

基于 Toolize 的 1000+ 真实软件工具包，构建一个面向 Agent 训练、rollout、评测和 ALE 打榜的真实软件环境平台，让模型在可执行、可验证、可复现的真实工具任务中持续进化。

更锋利的定位：

> Agent-World scales synthetic environments; SoftArena scales real executable software environments.

## 2. 背景

当前 Agent 训练和评测环境主要有几类：

- 合成多环境：强调自动生成环境、任务和 reward，代表方向是 Agent-World / AgentGym 类工作。
- API/tool-use benchmark：强调函数调用、业务 API、状态更新，代表方向是 ToolSandbox / tau-bench / ToolBench 类工作。
- 真实终端/电脑环境：强调 terminal、OS、web、desktop 操作，代表方向是 Terminal-Bench / OSWorld / WebArena 类工作。
- 垂直行业环境：强调金融、科学、表格、文档等专业任务。

这些工作证明了多环境 rollout、executable reward 和 tool-use training 的价值，但仍存在一个缺口：

**缺少一个基于大规模真实软件包生态的、可训练、可评测、可持续扩展的 Agent 环境底座。**

Toolize 已经把 1000+ 真实软件包适配成 Agent 可调用工具，这是稀缺资产。本项目要把这些工具从“工具集合”升级成“真实软件环境平台”。

## 3. 核心目标

### 3.1 产品目标

1. 支持快速接入大量真实软件环境。
2. 支持批量 rollout，产出可训练、可审计、可复现的轨迹数据。
3. 支持 verifier-first reward，把任务结果转成可靠训练信号。
4. 支持模型训练闭环：rollout -> scoring -> dataset -> SFT/RL/preference -> eval。
5. 支持 ALE-like 评测和打榜提交。
6. 支持按行业、能力、工具类型管理环境，避免环境数量增长后失控。

### 3.2 研究目标

回答一个核心问题：

> 真实软件生态中的可执行交互训练，能否让模型形成更可迁移的工具使用能力？

重点验证：

- seen tools 到 unseen tools 的迁移。
- seen industries 到 unseen industries 的迁移。
- single-tool 到 multi-tool workflow 的迁移。
- synthetic/API 训练与 real-software 训练的差异。
- verifier reward 相比 LLM judge / rubric reward 的稳定性和训练价值。

## 4. 非目标

- 不重写 Toolize 的底层工具适配。
- 不把每个软件包都机械做成独立环境。
- 不在第一阶段追求 GUI-heavy 任务。
- 不依赖人工主观评分作为主要 reward。
- 不把目标局限为 benchmark；平台必须能产训练数据并闭环提升模型。

## 5. 项目差异化

| 维度 | Agent-World 类工作 | 本项目 |
| --- | --- | --- |
| 环境来源 | 合成环境、动态任务生成 | 真实软件包、真实 CLI/MCP/文件系统状态 |
| 工具空间 | 由环境生成或手工定义 | 从 Toolize 1000+ 工具自动索引 |
| Reward | code execution、rubric、reference model | verifier-first，直接检查真实执行状态 |
| 任务组织 | 通用 agent arena | 行业 taxonomy + 能力 taxonomy + ALE-oriented suite |
| 主要价值 | 自动造环境 | 把真实软件世界变成可训练环境 |
| 数据资产 | 合成轨迹 | 真实软件操作轨迹 |
| 评测目标 | 通用 agent 能力 | ALE 打榜 + long-tail tool generalization |

本项目的 novelty 应钉在五点：

1. **Real software grounding**：不是 synthetic API，而是真实软件包和真实状态迁移。
2. **Tool-native environment construction**：从 MCP/tool schema 自动构建 action space。
3. **Verifier-first rollout**：环境天然产 executable reward。
4. **Industry-oriented environment taxonomy**：金融、医疗、法律、软件工程、系统运维等行业可扩展组织。
5. **Long-tail tool generalization**：训练模型适应大量未见过的长尾软件工具。

## 6. 总体架构

```text
Toolize 1000+ tools
        |
        v
Tool Registry --------------+
        |                    |
        v                    v
Environment Registry --> Rollout Orchestrator --> Trajectory Lake
        |                    |                         |
        v                    v                         v
Env Runtime/Sandbox --> Verifier Runner ----------> Dataset Builder
                                                        |
                                                        v
                                               SFT / DPO / RL Training
                                                        |
                                                        v
                                               Eval Suite / ALE Pack
```

核心模块：

- `Tool Registry`：扫描 Toolize 工具，索引 schema、类别、健康状态、side effect、timeout。
- `Environment Registry`：管理行业、环境、版本、split、entrypoint、工具 allowlist。
- `Runtime/Sandbox`：为每个 episode 创建隔离 workspace 和工具服务。
- `Rollout Orchestrator`：调度模型、环境和工具调用，记录完整轨迹。
- `Verifier Runner`：执行状态检查、隐藏测试、semantic diff、trace check。
- `Trajectory Lake`：保存 raw trajectory、verified episode、artifact、metrics。
- `Dataset Builder`：生成 SFT、preference、RL 数据。
- `Eval/ALE Pack`：本地评测、回归分析、ALE-like 提交包。

## 7. 项目结构

```text
softarena/
  registry/
    tools.py
    envs.py
    schemas.py
    env_index.generated.yaml
    env_index.lock

  envs/
    _shared/
      verifier_utils.py
      file_checks.py
      sql_checks.py
      dataset_utils.py
      docker_profiles.yaml

    finance/
      accounting_reconcile/
        v1/
          env.yaml
          tasks/
            train.yaml
            dev.yaml
            heldout.yaml
            stress.yaml
          init.py
          verifier.py
          README.md

    software_engineering/
      sqlite_data_repair/
        v1/
          env.yaml
          tasks/
          init.py
          verifier.py

    healthcare/
    legal/
    system_ops/
    science/
    office/

  runtime/
    sandbox.py
    mcp_client.py
    artifact_store.py

  rollout/
    runner.py
    scheduler.py
    trace.py
    policies.py

  training/
    datasets.py
    sft.py
    preference.py
    rl.py

  eval/
    suites.yaml
    evaluator.py
    report.py
    ale_pack.py

  cli.py

toolize/
  baseline/
  bin2mcp/
```

## 8. 环境管理设计

环境按四层管理：

```text
Domain -> Environment -> Version -> Split/Task
```

示例：

```text
finance.accounting_reconcile.v1
software_engineering.sqlite_data_repair.v1
system_ops.archive_forensics.v1
legal.contract_diff.v1
healthcare.clinical_table_cleaning.v1
```

### 8.1 环境最小文件

每个环境必须包含：

```text
env.yaml
tasks/train.yaml
tasks/dev.yaml
tasks/heldout.yaml
verifier.py
```

可选：

```text
init.py
tasks/stress.yaml
README.md
fixtures/
```

### 8.2 env.yaml 示例

```yaml
env_id: finance.accounting_reconcile.v1
domain: finance
version: 1
status: active

industry_tags:
  - accounting
  - reconciliation
  - audit

capability_tags:
  - spreadsheet
  - database
  - data-cleaning

tool_allowlist:
  - cli-db/sqlite3/sqlite_query
  - cli-db/sqlite3/sqlite_exec
  - cli-data/csvkit/csv_clean

entrypoint:
  init: init:create_episode
  verifier: verifier:verify

episode:
  max_steps: 30
  timeout_secs: 900
  workspace_policy: isolated_tmp

splits:
  train: tasks/train.yaml
  dev: tasks/dev.yaml
  heldout: tasks/heldout.yaml
  stress: tasks/stress.yaml

scoring:
  type: composite
  max_score: 1.0
```

## 9. 新环境自动发现机制

为避免环境多了之后 rollout 遗漏，采用三层机制：

### 9.1 自动扫描

平台扫描：

```text
softarena/envs/**/v*/env.yaml
```

只要新环境符合目录规范，就会被发现。

### 9.2 生成索引

命令：

```bash
softarena env discover
```

生成：

```text
softarena/registry/env_index.generated.yaml
```

示例：

```yaml
envs:
  - env_id: finance.accounting_reconcile.v1
    path: envs/finance/accounting_reconcile/v1
    domain: finance
    status: active
    splits: [train, dev, heldout, stress]
    eval_tier: core

  - env_id: software_engineering.sqlite_data_repair.v1
    path: envs/software_engineering/sqlite_data_repair/v1
    domain: software_engineering
    status: active
    splits: [train, dev, heldout]
    eval_tier: core
```

### 9.3 CI 防遗漏

PR 检查：

```bash
softarena env validate --all
softarena env discover --check
softarena rollout smoke --all-active
```

检查项：

- `env.yaml` schema 合法。
- `env_id` 与目录路径一致。
- `env_id` 全局唯一。
- `status: active` 的环境必须有 `train/dev/heldout`。
- `entrypoint` 可以 import。
- `verifier.py` 可以运行 smoke case。
- `tool_allowlist` 中的工具都存在于 Tool Registry。
- generated index 没有过期。

Rollout 只从 registry 查询环境：

```bash
softarena rollout run --suite all-active
softarena rollout run --domain finance
softarena rollout run --tag database
softarena rollout run --env finance.accounting_reconcile.v1
softarena rollout run --eval-tier core
```

## 10. Tool Registry 设计

输入来源：

- `toolize/baseline/*/*/config.toml`
- `toolize/bin2mcp/*-mcp`
- `toolize/baseline/reports/*.json`
- 运行时 `tools/list`

ToolSpec：

```yaml
tool_id: cli-db/sqlite3/sqlite_query
package: sqlite3
category: cli-db
transport: stdio_jsonrpc
schema:
  input: {...}
timeout_secs: 300
side_effect: read_only
determinism: deterministic
requires_network: false
requires_gui: false
health:
  build: pass
  smoke: pass
tags:
  - database
  - query
  - json-output
```

关键要求：

- 工具 schema 原样继承，环境只声明 allowlist。
- 补充 side effect、determinism、cost、health 等训练/评测元信息。
- registry 版本写入每条 trajectory。

## 11. Rollout 设计

Episode 生命周期：

1. 从 registry 选择环境和 split。
2. 根据 seed 生成任务实例。
3. 创建隔离 workspace。
4. 启动工具服务或容器。
5. 给模型暴露 task prompt 和 tool schema。
6. 循环执行 `model -> tool_call -> observation`。
7. 达到 final answer、step limit 或 timeout。
8. verifier 检查最终状态。
9. 写入 trajectory lake。

Trajectory Schema：

```json
{
  "episode_id": "...",
  "env_id": "software_engineering.sqlite_data_repair.v1",
  "task_id": "...",
  "seed": 123,
  "split": "train",
  "difficulty": "medium",
  "model": {
    "name": "model-v1",
    "checkpoint": "...",
    "sampling": {"temperature": 0.2}
  },
  "tool_registry_sha": "...",
  "env_registry_sha": "...",
  "steps": [
    {
      "index": 0,
      "tool_call": {"name": "sqlite_query", "arguments": {}},
      "observation": {"ok": true, "content": "..."},
      "latency_ms": 120
    }
  ],
  "verifier": {
    "score": 1.0,
    "passed": true,
    "checks": [],
    "diagnostics": ""
  },
  "artifacts": {
    "workspace_ref": "...",
    "logs_ref": "..."
  }
}
```

## 12. Verifier 设计

Verifier 是本项目的核心壁垒之一。

类型：

- `state verifier`：检查文件、数据库、目录、配置最终状态。
- `unit test verifier`：运行隐藏测试。
- `semantic verifier`：比较 JSON/CSV/SQL/PDF/text 的语义等价。
- `trace verifier`：检查工具使用行为和禁用操作。
- `composite verifier`：多项检查加权，支持 partial credit。

返回：

```python
class VerificationResult:
    score: float
    passed: bool
    checks: list[CheckResult]
    diagnostics: str
    metrics: dict
```

硬性要求：

- verifier 重跑一致率 > 99%。
- verifier 不泄漏 hidden answer。
- eval split verifier 只读。
- verifier 失败要能区分环境错误和模型错误。

## 13. 首批环境规划

MVP 环境建议：

| 环境 | 行业/能力 | 工具 | 验证方式 |
| --- | --- | --- | --- |
| `software_engineering.sqlite_data_repair.v1` | 数据库/软件工程 | sqlite3 | schema + SQL result |
| `system_ops.archive_forensics.v1` | 系统运维/文件处理 | tar/gzip/file/sha | hash + metadata |
| `office.text_transform.v1` | 文档/数据清洗 | sed/awk/jq/csvkit | semantic diff |
| `software_engineering.build_fix.v1` | 编译调试 | make/gcc/clang/bear | hidden tests |
| `network.dns_debug.v1` | 网络诊断 | dig/curl/openssl | mocked service + report |
| `finance.accounting_reconcile.v1` | 金融/对账 | sqlite/csv/spreadsheet | balance check + audit report |

第一阶段优先选择 deterministic、无网络、可自动验证的环境。

## 14. 训练 Pipeline

数据分层：

```text
raw_trajectory
  -> verified_episode
  -> train_sample
  -> preference_pair
  -> rl_episode
```

训练阶段：

1. **SFT**：用高分轨迹训练工具调用格式和任务策略。
2. **Preference training**：同任务多轨迹构造 chosen/rejected。
3. **RL**：terminal reward 来自 verifier score，step penalty 控制无效工具调用。
4. **Curriculum**：根据 pass rate 自动提高任务难度。

数据过滤：

- 保留 pass 或高 partial score 轨迹。
- 保留有价值失败轨迹用于 preference/rejection。
- 剔除环境错误、工具服务错误、verifier 不稳定任务。
- 剔除泄漏 hidden answer 的任务。

## 15. 评测与 ALE 打榜

评测 split：

- `smoke`：检查环境和工具可用。
- `dev`：日常迭代。
- `heldout`：冻结，不进训练。
- `stress`：长链路、多工具、资源压力。

指标：

- `pass@1`
- `pass@k`
- 平均 verifier score
- 工具调用成功率
- 平均 step 数
- timeout rate
- regression win/loss/tie
- 按 domain/capability/tool/difficulty 分桶

ALE Pack：

```text
eval/ale_pack.py
  -> submission_manifest.json
  -> trajectories.jsonl
  -> answers.jsonl
  -> env_registry_sha
  -> tool_registry_sha
  -> model_checkpoint
```

提交前必须检查：

- eval split 没有进入训练。
- 所有任务 seed 和环境版本固定。
- verifier 版本固定。
- 模型 checkpoint、代码 commit、registry sha 可追溯。

## 16. 成功指标

### 16.1 两个月内必须证明

- 3-6 个环境端到端跑通。
- 每个环境至少 50 train / 20 dev / 20 heldout。
- verifier 重跑一致率 > 99%。
- rollout 轨迹可复现。
- SFT 或 preference training 后 heldout 有稳定提升。

### 16.2 六个月目标

- 30-50 个环境。
- 100k+ verified trajectories。
- 覆盖 5+ 行业、8+ 能力类。
- 在 ALE-like heldout suite 上持续涨分。
- 支持自动失败聚类和定向环境扩展。

### 16.3 十二个月目标

- 100+ 环境族。
- 1M+ verified trajectories。
- 支持 seen -> unseen tools 泛化实验。
- 形成开放 benchmark / dataset / leaderboard。
- 冲 NeurIPS/ICML/ICLR/COLM 或 Nature Machine Intelligence 级别论文。

## 17. 里程碑

### M0：项目骨架

- 实现 schema。
- 实现 tool registry scanner。
- 实现 env discovery。
- 实现 mock model + fake env smoke。

验收：

```bash
softarena list-tools
softarena env discover
softarena rollout run --env fake.v1 --model mock
```

### M1：MVP 环境

- 接入 sqlite、archive、text transform。
- 实现 deterministic verifier。
- 产出第一批 verified trajectories。

验收：

- 三个环境端到端 rollout。
- 轨迹可复现。
- verifier 重跑一致。

### M2：训练闭环

- 实现 dataset builder。
- 实现 SFT/preference 数据导出。
- 训练第一个模型版本。

验收：

- heldout pass rate 有显著提升。
- 能生成模型对比报告。

### M3：多行业扩展

- 接入 finance、software_engineering、system_ops、office、network。
- 实现 domain/capability eval suite。
- 实现 failure mining。

验收：

- 10+ 环境。
- 按行业/能力输出评测报告。

### M4：ALE 打榜

- 实现 ALE pack。
- 固定 heldout suite。
- 生成提交 manifest。

验收：

- 可复现生成 ALE-like 提交包。
- 每次提交可追溯模型、代码、环境和工具版本。

## 18. 风险

| 风险 | 表现 | 对策 |
| --- | --- | --- |
| 只像 environment zoo | 有很多环境但训练没涨分 | 两个月内必须验证 data flywheel |
| verifier 不稳定 | reward 噪声大 | deterministic sandbox + verifier rerun |
| 工具质量不一 | false negative 多 | tool health gating |
| 环境接入太慢 | 扩展成本高 | env.yaml + 自动发现 + shared verifier utils |
| eval 污染 | 榜单虚高 | split 隔离 + manifest + dataset audit |
| 与 Agent-World 撞车 | novelty 不清 | 强调 real software substrate 和 long-tail tools |

## 19. 投稿与发布策略

现实路径：

1. 第一篇：系统/benchmark/data paper。
   - 目标：NeurIPS Datasets & Benchmarks、ICLR、COLM、ACL/EMNLP。
   - 贡献：real software arena、verifier-first rollout、环境 registry、初步训练收益。

2. 第二篇：训练/迁移能力论文。
   - 目标：ICML/NeurIPS/ICLR 或 Nature Machine Intelligence。
   - 贡献：证明真实软件交互训练带来可迁移工具智能。

Nature 主刊不是近期目标。若要冲更高，需要把项目从平台贡献升级为科学发现：

> 真实软件生态交互如何驱动通用工具智能涌现与迁移。

## 20. 决策建议

建议采用阶段性下注：

- 先投入 2-3 周做 infra skeleton。
- 再投入 6-8 周验证 data flywheel。
- 如果训练后 heldout/ALE-like eval 稳定涨分，继续投入 6-12 个月。
- 如果只得到很多环境但训练不涨分，则收缩为 benchmark/eval 项目。

Go / No-Go 标准：

```text
Go:
  verifier 稳定
  rollout 成本可控
  训练后 heldout 涨分
  unseen tool/domain 有迁移

No-Go:
  环境维护成本过高
  verifier 噪声过大
  数据训练无收益
  只能靠人工挑任务提升
```

