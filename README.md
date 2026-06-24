# SoftArena

SoftArena is a real software environment arena for verifiable agent rollout,
training data generation, and ALE-style evaluation.

The first MVP environment is:

- `software_engineering.sqlite_data_repair.v1`

It demonstrates the initial end-to-end loop:

```bash
python3 -m softarena list-envs
python3 -m softarena list-tools
python3 -m softarena env discover

# Roll out a configured batch job.
python3 -m softarena rollout batch --job configs/rollout/sqlite_smoke.json

# Build trainable datasets from verified trajectories.
python3 -m softarena dataset build \
  --kind sft \
  --input-dir runs/rollouts/sqlite_smoke_rollout_v1/trajectories.jsonl \
  --output datasets/sft/sqlite_smoke.jsonl

python3 -m softarena dataset build \
  --kind reward \
  --input-dir runs/rollouts/sqlite_smoke_rollout_v1/trajectories.jsonl \
  --output datasets/reward/sqlite_smoke.jsonl

# Run the first training recipe. The MVP trainer is a dry run that validates
# datasets and writes model manifests/metrics without requiring GPU deps.
python3 -m softarena train run --recipe configs/training/sft_sqlite_smoke.json
python3 -m softarena train list --models-dir models
```

Current MVP components:

- Tool registry scanner for Toolize `config.toml` files.
- Environment discovery from `softarena/envs/**/v*/env.json`.
- Configured rollout jobs under `configs/rollout/`.
- Local SQLite tool runtime for smoke rollout.
- Deterministic verifier for database state.
- Trajectory JSON and JSONL output under `runs/`.
- Dataset builders for SFT and verifier reward JSONL.
- Training recipes under `configs/training/` with a dry-run trainer interface.

`toolize/` is treated as an external dependency because it is a large tool
corpus with its own repository.

## verl Trainer Adapter

SoftArena can prepare verl training runs for SFT, reward-filtered SFT (RFT),
and GRPO:

```bash
python3 -m softarena train run --recipe configs/training/verl_sft_sqlite_smoke.json
python3 -m softarena train run --recipe configs/training/verl_rft_sqlite_smoke.json
python3 -m softarena train run --recipe configs/training/verl_grpo_sqlite_smoke.json
```

By default these commands prepare verl-formatted data, a `train_manifest.json`,
and a `launch_verl.sh` script under `models/`. To actually launch verl on a
GPU machine with verl installed, add `--execute`:

```bash
python3 -m softarena train run --recipe configs/training/verl_sft_sqlite_smoke.json --execute
```

The MVP GRPO adapter uses `softarena/training/verl_reward.py` as the reward hook.
Production GRPO should replace that hook with a verifier-backed reward that
executes candidate tool trajectories in isolated SoftArena environments.

## Local Smoke Test

On macOS, use the doctor command to validate the local code path without running
GPU training:

```bash
python3 -m softarena doctor
```

It compiles Python sources, discovers registries, runs the SQLite rollout, builds
SFT/reward datasets, runs the dry-run trainer, and prepares verl SFT/GRPO launchers.
The latest report is written to `runs/doctor/latest.json`.

## MVP Environments

SoftArena currently includes six smoke-tested MVP environments:

| Environment | Capability | Verifier |
| --- | --- | --- |
| `software_engineering.sqlite_data_repair.v1` | SQLite data repair | schema + SQL result |
| `system_ops.archive_forensics.v1` | archive/file forensics | hash + metadata |
| `office.text_transform.v1` | text/CSV cleanup | semantic JSONL diff |
| `software_engineering.build_fix.v1` | C build debugging | `make test` hidden check |
| `network.dns_debug.v1` | mocked DNS diagnosis | root cause + remediation report |
| `finance.accounting_reconcile.v1` | accounting reconciliation | balance table check |

Run all local smoke checks with:

```bash
python3 -m softarena doctor
```

## Toolize Runtime

SoftArena now separates tool metadata from tool execution:

- Tool metadata comes from `toolize/baseline/*/*/config.toml`.
- `LocalToolizeRuntime` exposes a stable `runtime.call(tool_id, arguments)` interface.
- Current local backend executes stable real binaries such as `sqlite3`, `tar`, `file`, `sha256`, and `make`.
- Future Docker/MCP backends should implement the same runtime interface, so environments do not change.

You can smoke-test the runtime directly:

```bash
tmpdb=$(mktemp /tmp/softarena_toolize.XXXX.db)
python3 -m softarena tool call \
  --tool cli-db/sqlite3/sqlite_exec \
  --args "{\"db_path\":\"$tmpdb\",\"sql\":\"CREATE TABLE t(x INTEGER); INSERT INTO t VALUES (1);\"}"
python3 -m softarena tool call \
  --tool cli-db/sqlite3/sqlite_query \
  --args "{\"db_path\":\"$tmpdb\",\"sql\":\"SELECT x FROM t\"}"
```

### Docker JSON-RPC Backend

For real Toolize containers, switch the runtime backend to `toolize_docker`:

```bash
python3 -m softarena tool call \
  --runtime toolize_docker \
  --tool cli-db/sqlite3/sqlite_query \
  --args '{"db_path":"/workspace/test.db","sql":"SELECT 1 AS x"}'

python3 -m softarena rollout batch \
  --job configs/rollout/sqlite_smoke.json \
  --runtime toolize_docker
```

The Docker backend sends JSON-RPC 2.0 over stdin/stdout to:

```bash
docker run --rm -i mass-toolize/<package>
```

By default images resolve as `mass-toolize/<package>`. Override the prefix with:

```bash
export SOFTARENA_TOOLIZE_IMAGE_PREFIX=your-registry/mass-toolize
```

Episode workspaces are mounted into containers at `/workspace`, and absolute host
paths under the episode workspace are rewritten to container paths before calling
Toolize. The backend is intentionally per-call for the MVP; a warm container or
UDS backend can implement the same `runtime.call(tool_id, arguments)` interface.
