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
python3 -m softarena rollout run \
  --env software_engineering.sqlite_data_repair.v1 \
  --split smoke \
  --model scripted-sqlite-v0 \
  --output-dir runs/smoke
```

Current MVP components:

- Tool registry scanner for Toolize `config.toml` files.
- Environment discovery from `softarena/envs/**/v*/env.json`.
- Local SQLite tool runtime for smoke rollout.
- Deterministic verifier for database state.
- Trajectory JSON output under `runs/`.

`toolize/` is treated as an external dependency because it is a large tool
corpus with its own repository.
