# SoftArena

SoftArena 是一个面向真实软件环境的 Agent arena，用于可验证 rollout、
训练数据生成、任务 seed 构建，以及 ALE 风格评测。

当前 v0 切片包含一组确定性 smoke 环境，以及一个 Computing & Mathematical
Sciences 任务 seed 构建链路：

- `computing_math.project_sync_sqlite.v0`
- `computing_math.weighted_metrics.v0`
- `software_engineering.sqlite_data_repair.v1`
- `system_ops.archive_forensics.v1`
- `office.text_transform.v1`
- `software_engineering.build_fix.v1`
- `network.dns_debug.v1`
- `finance.accounting_reconcile.v1`

本地 smoke 路径覆盖完整闭环：

```bash
python3 -m softarena list-envs
python3 -m softarena list-tools
python3 -m softarena env discover
python3 -m softarena doctor

# 跑一个配置化 rollout job。
python3 -m softarena rollout batch --job configs/rollout/sqlite_smoke.json
python3 -m softarena rollout batch --job configs/rollout/computing_math_project_sync_sqlite_smoke.json

# 从已验证轨迹构建训练数据。
python3 -m softarena dataset build \
  --kind sft \
  --input-dir runs/rollouts/sqlite_smoke_rollout_v1/trajectories.jsonl \
  --output datasets/sft/sqlite_smoke.jsonl

python3 -m softarena dataset build \
  --kind reward \
  --input-dir runs/rollouts/sqlite_smoke_rollout_v1/trajectories.jsonl \
  --output datasets/reward/sqlite_smoke.jsonl

# 第一版训练 recipe 是 dry run：验证数据集并写出模型 manifest/metrics，
# 不要求 GPU 依赖。
python3 -m softarena train run --recipe configs/training/sft_sqlite_smoke.json
python3 -m softarena train list --models-dir models
```

当前 MVP 组件：

- Toolize `config.toml` / `bin2mcp` 工具注册扫描。
- 从 `softarena/envs/**/v*/env.json` 自动发现环境。
- `configs/rollout/` 下的配置化 rollout jobs。
- 本地 SQLite tool runtime，用于 smoke rollout。
- Computing Math v0 环境：隔离 workspace 初始化 + 确定性 SQLite verifier。
- `softarena.search_agent`：基于 ALE/toolize 报告、私有 demand-source 切片和在线 research 构建 tool-aligned seed library。
- Claude Code 兼容 executor adapter：通过本地外部 harness 执行 episode，不把 harness vendored 进本仓库。
- 最小 Toolize MCP bridge：覆盖 `sqlite3`、`jq`、`rg`、`gawk`/`mawk`、`js-yaml`、`shellcheck`、`pylint`、`cppcheck`、`gcovr`、`ab`、`nginx`、`diffstat` 等 CLI 工具入口。
- 数据库状态的确定性 verifier。
- `runs/` 下的 trajectory JSON / JSONL 输出。
- SFT 与 verifier reward JSONL 数据构建器。
- `configs/training/` 下的训练 recipes 和 dry-run trainer 接口。

`toolize/` 被视为外部依赖；它是一个大型工具语料库，有自己的仓库和发布节奏。

私有生产代码、私有 demand 数据、模型 endpoint 和 API key 不提交到本仓库。
运行时集成通过环境变量和本地路径注入。

## Computing Math v0

主 v0 垂直切片是 `computing_math.project_sync_sqlite.v0`。它的 frozen
smoke split 包含 50 条由 searchAgent seed 派生的合成任务。

每条 episode 的运行过程：

1. 为 episode 创建隔离临时 workspace。
2. 写入确定性 workspace materials 和 SQLite 数据库。
3. prompt executor 检查 `artifact_requirements`。
4. 要求创建 `project_sync_report` 表，并为每个 artifact 写一条 `ready` 记录。
5. 要求创建 `report_status` 表，并包含 `ready` 状态。
6. verifier 对最终 SQLite 状态做确定性检查。

直接运行：

```bash
python3 -m softarena rollout batch \
  --job configs/rollout/computing_math_project_sync_sqlite_smoke.json
```

`computing_math.weighted_metrics.v0` 是一个更小的确定性 SQLite 环境，用于保留
紧凑的数值计算 smoke 任务。

## searchAgent Seed Builder

`softarena.search_agent` 负责构建下游任务生成用的 seed library。它不直接写最终
SoftArena task。

设计链路是：

```text
ALE/toolize 报告 + demand-source 切片 + LLM/web search + anysearch
  -> seed specs
  -> diversity task prompts
  -> 外部/私有 task builder 或确定性 finalizer
  -> frozen SoftArena task split
  -> init.py 创建 workspace
  -> executor 生成 trajectory
  -> verifier 产出 report
```

在线运行需要一个 Responses-compatible research endpoint：

```bash
export RESEARCH_API_KEY=...
export RESEARCH_BASE_URL=http://localhost:3003/v1
export RESEARCH_MODEL=gpt-5.5
export SOFTARENA_DEMAND_SOURCE=/path/to/private/demand_source

python3 -m softarena.search_agent build \
  --reports-dir /path/to/ale_toolize_reports \
  --demand-source "$SOFTARENA_DEMAND_SOURCE" \
  --output runs/search_agent/seed_library \
  --target-count 8
```

可选参数：

```bash
export RESEARCH_WEB_SEARCH_TOOL=web_search
export ANYSEARCH_COMMAND=anysearch
export SEARCH_AGENT_LLM_BATCH_SIZE=2
```

离线验证可以加 `--offline`。离线模式会从本地报告生成确定性 fallback evidence，
不调用在线 research。

## 外部 Executor Adapter

`softarena/claudecode_adapter.py` 把一个 SoftArena episode 接到外部 Claude
Code-compatible executor harness。

adapter 的职责很窄：

- 接收已经初始化好的 episode workspace。
- 把 episode prompt 传给外部 harness。
- 写入 MCP config。
- 做 timeout 和进程终止处理。
- 记录 `session_stream.jsonl`、`stderr.log`、`toolize_calls.jsonl` 和 `claudecode_report.json`。

executor harness 本体不 vendored 到仓库。运行时这样配置：

```bash
export SOFTARENA_EXECUTOR_HARNESS_DIR=/path/to/local/executor_harness
export SOFTARENA_EXECUTOR_CONFIG=/path/to/executor.toml
export SOFTARENA_TOOLIZE_MCP_SERVER=/path/to/SoftArena/softarena/toolize_mcp_server.py
```

如果 `claude` CLI 或 harness script 不可用，adapter 会写出 `blocked` report，
而不是静默失败。

## verl Trainer Adapter

SoftArena 可以准备 verl 格式的 SFT、reward-filtered SFT(RFT) 和 GRPO 训练运行：

```bash
python3 -m softarena train run --recipe configs/training/verl_sft_sqlite_smoke.json
python3 -m softarena train run --recipe configs/training/verl_rft_sqlite_smoke.json
python3 -m softarena train run --recipe configs/training/verl_grpo_sqlite_smoke.json
```

默认情况下，这些命令只准备 verl 数据、`train_manifest.json` 和 `launch_verl.sh`，
输出到 `models/`。如果在已安装 verl 的 GPU 机器上真实启动训练，加 `--execute`：

```bash
python3 -m softarena train run --recipe configs/training/verl_sft_sqlite_smoke.json --execute
```

当前 MVP GRPO adapter 使用 `softarena/training/verl_reward.py` 作为 reward hook。
生产级 GRPO 应替换为 verifier-backed reward：在隔离 SoftArena 环境中执行候选
tool trajectory 并评分。

## SoftArena Smoke Evaluation

使用确定性 scripted baseline 跑本地 SoftArena smoke suite：

```bash
python3 -m softarena eval run --suite configs/eval/softarena_smoke_scripted.json
```

使用 Responses API 模型跑同一套 suite：

```bash
export OPENAI_API_KEY=...
python3 -m softarena eval run --suite configs/eval/softarena_smoke_gpt55.json
```

eval runner 会在 `runs/eval/<run_id>/` 下写出 `report.json`、`leaderboard.csv`
和 `trajectories.jsonl`。如果缺少 credential 或模型不可用，该 run 会标记为
`blocked`，并跳过 episodes，而不是计入模型分数。

OpenAI eval 路径使用 JSON-action tool loop。每一步模型必须返回：

```json
{"rationale": "...", "tool": "...", "arguments": {...}}
```

其中 `tool` 必须来自环境 allowlist 的 Toolize `bin2mcp/...` tool id；任务完成时
返回：

```json
{"final_answer": "..."}
```

## Agents' Last Exam

Agents' Last Exam 是外部 benchmark，不是 SoftArena smoke suite。不要把
`softarena_smoke_*` configs 当成 ALE 替代。请本地 clone 官方 harness，并让
SoftArena 指向该 checkout：

```bash
git clone --depth 1 https://github.com/rdi-berkeley/agents-last-exam.git \
  external/agents-last-exam

python3 -m softarena eval agents-last-exam \
  --model dummy \
  --repo-dir external/agents-last-exam \
  --dry-run
```

adapter 调用的官方命令是：

```bash
uv run python -m ale_run run local_dummy_docker_exp.yaml [--dry-run]
```

默认生成的 experiment 使用官方 `dummy` agent、Docker Linux environment 和
`selected_tasks/helloworld.txt`。真实运行需要 Docker 和 ALE task data access，
具体以官方 repo 说明为准。如果缺少 Docker、task data 或 cloud credentials，
SoftArena 会写出 `blocked` ALE report，并保留官方 stdout/stderr。

## 本地 Smoke Test

使用 doctor 命令验证本地代码路径，不需要跑 GPU 训练：

```bash
python3 -m softarena doctor
```

它会编译 Python 源码、发现 registries、验证 tool ids、运行所有配置化 smoke
rollouts、构建 SFT/reward 数据集、运行 dry-run trainer，并准备 verl SFT/GRPO
launchers。最新报告写入 `runs/doctor/latest.json`。

## MVP Environments

SoftArena 当前包含 8 个 smoke-tested MVP environments：

| Environment | Capability | Verifier |
| --- | --- | --- |
| `computing_math.project_sync_sqlite.v0` | searchAgent 派生的项目/artifact 同步任务 | SQLite report/status checks |
| `computing_math.weighted_metrics.v0` | 加权指标计算 | SQL result check |
| `software_engineering.sqlite_data_repair.v1` | SQLite 数据修复 | schema + SQL result |
| `system_ops.archive_forensics.v1` | archive/file forensics | hash + metadata |
| `office.text_transform.v1` | text/CSV cleanup | semantic JSONL diff |
| `software_engineering.build_fix.v1` | C build debugging | `make test` hidden check |
| `network.dns_debug.v1` | mocked DNS diagnosis | root cause + remediation report |
| `finance.accounting_reconcile.v1` | accounting reconciliation | balance table check |

运行全部本地 smoke checks：

```bash
python3 -m softarena doctor
```

## Toolize Runtime

SoftArena 将工具元数据和工具执行分开：

- 工具元数据优先从真实 Toolize adapters `toolize/bin2mcp/*-mcp` 发现。
- Tool id 使用 `bin2mcp/<adapter-dir>/<mcp-tool-name>`，例如 `bin2mcp/file-mcp/identify_file`。
- 如果 `bin2mcp` 不存在，registry 会 fallback 到旧的 `toolize/baseline/*/*/config.toml` metadata。
- 如果外部 Toolize corpus 未安装，内置 MVP tool specs 会保持仓库自测可运行。
- `LocalToolizeRuntime` 暴露稳定的 `runtime.call(tool_id, arguments)` 接口，用于本地 smoke tests。
- Docker/MCP backends 实现同一个 runtime interface，因此环境代码无需变化。

直接 smoke-test runtime：

```bash
tmpdb=$(mktemp /tmp/softarena_toolize.XXXX.db)
python3 -m softarena tool call \
  --tool bin2mcp/postgresql-client-mcp/sql_execute \
  --args "{\"db_path\":\"$tmpdb\",\"sql\":\"CREATE TABLE t(x INTEGER); INSERT INTO t VALUES (1);\"}"
python3 -m softarena tool call \
  --tool bin2mcp/postgresql-client-mcp/sql_execute \
  --args "{\"db_path\":\"$tmpdb\",\"sql\":\"SELECT x FROM t\"}"
```

### Docker JSON-RPC Backend

真实 Toolize containers 可通过 `toolize_docker` runtime backend 调用：

```bash
python3 -m softarena tool call \
  --runtime toolize_docker \
  --tool bin2mcp/postgresql-client-mcp/sql_execute \
  --args '{"db_path":"/workspace/test.db","sql":"SELECT 1 AS x"}'

python3 -m softarena rollout batch \
  --job configs/rollout/sqlite_smoke.json \
  --runtime toolize_docker
```

Docker backend 通过 stdin/stdout 发送 JSON-RPC 2.0：

```bash
docker run --rm -i mass-toolize/<package>
```

默认 image 解析为 `mass-toolize/<package>`。可以用环境变量覆盖前缀：

```bash
export SOFTARENA_TOOLIZE_IMAGE_PREFIX=your-registry/mass-toolize
```

Episode workspaces 会挂载到 container 的 `/workspace`，并且 episode workspace
下的绝对 host path 会在调用 Toolize 前重写成 container path。当前 backend 为 MVP
采用 per-call 方式；后续 warm container 或 UDS backend 也可以实现同一套
`runtime.call(tool_id, arguments)` 接口。

## Tool ID Validation

环境 `tool_allowlist` 必须是 registry 可发现的真实 Toolize tool id。验证命令：

```bash
python3 -m softarena env validate-tools
```

`python3 -m softarena doctor` 会在 rollout 前运行该验证，因此 fake 或拼错的 tool id
会 fail fast。
