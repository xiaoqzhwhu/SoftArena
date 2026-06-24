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
