from __future__ import annotations

import csv
import hashlib
import json
import mimetypes
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Any

from softarena.registry.envs import EnvSpec, load_entrypoint
from softarena.runtime.sqlite_tools import call_sqlite_tool


def load_tasks(env: EnvSpec, split: str) -> list[dict[str, Any]]:
    if split not in env.splits:
        raise ValueError(f"Env {env.env_id} has no split: {split}")
    task_path = env.path / env.splits[split]
    payload = json.loads(task_path.read_text())
    return list(payload["tasks"])


def run_episode(
    env: EnvSpec,
    task: dict[str, Any],
    model: str,
    output_dir: Path,
    split: str = "smoke",
    seed: int = 0,
    policy: str = "scripted_sqlite",
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    init_fn = load_entrypoint(env, env.entrypoint["init"])
    verify_fn = load_entrypoint(env, env.entrypoint["verifier"])

    with tempfile.TemporaryDirectory(prefix="softarena_") as tmp:
        workspace = Path(tmp)
        episode = init_fn(task, workspace)
        start_time = time.time()
        steps = run_scripted_policy(policy, env.env_id, episode)
        verifier = verify_fn(episode)
        elapsed_ms = int((time.time() - start_time) * 1000)
        final_answer = "Created customer_revenue and idx_customer_revenue_customer_id."

        trajectory = {
            "episode_id": f"{env.env_id}:{task['task_id']}:seed{seed}",
            "env_id": env.env_id,
            "env_version": env.version,
            "task_id": task["task_id"],
            "split": split,
            "seed": seed,
            "difficulty": task.get("difficulty", "unknown"),
            "model": {"name": model, "kind": "scripted", "policy": policy},
            "prompt": episode["prompt"],
            "messages": build_training_messages(episode["prompt"], steps, final_answer),
            "steps": steps,
            "final_answer": final_answer,
            "verifier": verifier,
            "elapsed_ms": elapsed_ms,
        }

        out_path = output_dir / f"{task['task_id']}_seed{seed}.json"
        out_path.write_text(json.dumps(trajectory, indent=2, ensure_ascii=False) + "\n")
        return trajectory


def run_scripted_policy(policy: str, env_id: str, episode: dict[str, Any]) -> list[dict[str, Any]]:
    if policy == "auto":
        policy = {
            "software_engineering.sqlite_data_repair.v1": "scripted_sqlite",
            "system_ops.archive_forensics.v1": "scripted_archive_forensics",
            "office.text_transform.v1": "scripted_text_transform",
            "software_engineering.build_fix.v1": "scripted_build_fix",
            "network.dns_debug.v1": "scripted_dns_debug",
            "finance.accounting_reconcile.v1": "scripted_accounting_reconcile",
        }.get(env_id, "scripted_sqlite")
    policies = {
        "scripted_sqlite": scripted_sqlite_policy,
        "scripted_archive_forensics": scripted_archive_forensics_policy,
        "scripted_text_transform": scripted_text_transform_policy,
        "scripted_build_fix": scripted_build_fix_policy,
        "scripted_dns_debug": scripted_dns_debug_policy,
        "scripted_accounting_reconcile": scripted_accounting_reconcile_policy,
    }
    if policy not in policies:
        raise ValueError(f"Unsupported policy: {policy}")
    return policies[policy](episode)


def make_step(index: int, name: str, arguments: dict[str, Any], rationale: str, observation: dict[str, Any]) -> dict[str, Any]:
    return {"index": index, "rationale": rationale, "tool_call": {"name": name, "arguments": arguments}, "observation": observation, "latency_ms": 0}


def scripted_archive_forensics_policy(episode: dict[str, Any]) -> list[dict[str, Any]]:
    archive_path = Path(episode["archive_path"])
    extract_dir = Path(episode["extract_dir"]); extract_dir.mkdir(parents=True, exist_ok=True)
    steps = []
    with tarfile.open(archive_path, "r:gz") as tar:
        members = tar.getnames(); tar.extractall(extract_dir)
    steps.append(make_step(0, "tar_extract", {"archive_path": str(archive_path), "output_dir": str(extract_dir)}, "Extract the archive so files can be inspected.", {"ok": True, "members": members}))
    evidence = extract_dir / members[0]
    file_type = mimetypes.guess_type(evidence.name)[0] or "ASCII text"
    digest = hashlib.sha256(evidence.read_bytes()).hexdigest()
    steps.append(make_step(1, "file_identify", {"path": str(evidence)}, "Identify the extracted evidence file type.", {"ok": True, "file_type": file_type}))
    steps.append(make_step(2, "sha256sum", {"path": str(evidence)}, "Hash the evidence to make the report reproducible.", {"ok": True, "sha256": digest}))
    Path(episode["report_path"]).write_text(json.dumps({"evidence_file": evidence.name, "sha256": digest, "file_type": "ASCII text"}, indent=2) + "\n")
    steps.append(make_step(3, "write_report", {"path": episode["report_path"]}, "Write the final forensic report.", {"ok": True}))
    return steps


def scripted_text_transform_policy(episode: dict[str, Any]) -> list[dict[str, Any]]:
    input_path = Path(episode["input_path"]); output_path = Path(episode["output_path"])
    with input_path.open() as f:
        rows = list(csv.DictReader(f))
    active = [{"id": r["id"], "name": r["name"], "email": r["email"].lower()} for r in rows if r["status"] == "active"]
    output_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in active))
    return [
        make_step(0, "csv_read", {"path": str(input_path)}, "Read the CSV rows before filtering.", {"ok": True, "rows": len(rows)}),
        make_step(1, "jq_transform", {"filter": "status == active; email lowercase"}, "Filter active contacts and normalize email addresses.", {"ok": True, "rows": len(active)}),
        make_step(2, "write_jsonl", {"path": str(output_path)}, "Write the semantic JSONL output.", {"ok": True}),
    ]


def scripted_build_fix_policy(episode: dict[str, Any]) -> list[dict[str, Any]]:
    project = Path(episode["project_dir"]); source = Path(episode["source_path"])
    before = subprocess.run(["make", "test"], cwd=project, text=True, capture_output=True, check=False, timeout=30)
    source.write_text(source.read_text().replace("return a - b;", "return a + b;"))
    after = subprocess.run(["make", "test"], cwd=project, text=True, capture_output=True, check=False, timeout=30)
    return [
        make_step(0, "make_test", {"cwd": str(project)}, "Run the hidden-equivalent build test to reproduce the failure.", {"ok": before.returncode == 0, "returncode": before.returncode, "stderr": before.stderr}),
        make_step(1, "edit_source", {"path": str(source)}, "Fix the arithmetic bug in the source file.", {"ok": True}),
        make_step(2, "make_test", {"cwd": str(project)}, "Run tests again after the source fix.", {"ok": after.returncode == 0, "returncode": after.returncode, "stdout": after.stdout, "stderr": after.stderr}),
    ]


def scripted_dns_debug_policy(episode: dict[str, Any]) -> list[dict[str, Any]]:
    evidence = json.loads(Path(episode["evidence_path"]).read_text())
    report = {"root_cause": "stale_dns_record", "remediation": f"update {evidence['domain']} A record to {evidence['http_connect_ip']}"}
    Path(episode["report_path"]).write_text(json.dumps(report, indent=2) + "\n")
    return [
        make_step(0, "dig", {"domain": evidence["domain"]}, "Check the mocked DNS answer.", {"ok": True, "answer": evidence["dns_answer"]}),
        make_step(1, "curl", {"domain": evidence["domain"]}, "Compare the service endpoint observed by HTTP evidence.", {"ok": True, "connect_ip": evidence["http_connect_ip"]}),
        make_step(2, "write_report", {"path": episode["report_path"]}, "Report the stale DNS record and remediation.", {"ok": True}),
    ]


def scripted_accounting_reconcile_policy(episode: dict[str, Any]) -> list[dict[str, Any]]:
    sql = """
    DROP TABLE IF EXISTS reconciliation_report;
    CREATE TABLE reconciliation_report AS
    WITH l AS (SELECT account_id, ROUND(SUM(amount), 2) AS ledger_total FROM ledger GROUP BY account_id),
         b AS (SELECT account_id, ROUND(SUM(amount), 2) AS bank_total FROM bank GROUP BY account_id),
         accounts AS (SELECT account_id FROM ledger UNION SELECT account_id FROM bank)
    SELECT a.account_id,
           COALESCE(l.ledger_total, 0.0) AS ledger_total,
           COALESCE(b.bank_total, 0.0) AS bank_total,
           ROUND(COALESCE(l.ledger_total, 0.0) - COALESCE(b.bank_total, 0.0), 2) AS difference,
           CASE WHEN ROUND(COALESCE(l.ledger_total, 0.0) - COALESCE(b.bank_total, 0.0), 2) = 0 THEN 'balanced' ELSE 'mismatch' END AS status
    FROM accounts a LEFT JOIN l USING(account_id) LEFT JOIN b USING(account_id);
    """
    obs = call_sqlite_tool("sqlite_exec", {"db_path": episode["db_path"], "sql": sql})
    query = call_sqlite_tool("sqlite_query", {"db_path": episode["db_path"], "sql": "SELECT * FROM reconciliation_report ORDER BY account_id"})
    return [
        make_step(0, "sqlite_exec", {"db_path": episode["db_path"], "sql": sql}, "Aggregate ledger and bank totals into a reconciliation report.", obs),
        make_step(1, "sqlite_query", {"db_path": episode["db_path"], "sql": "SELECT * FROM reconciliation_report ORDER BY account_id"}, "Inspect the final reconciliation rows.", query),
    ]


def scripted_sqlite_policy(episode: dict[str, Any]) -> list[dict[str, Any]]:
    db_path = episode["db_path"]
    actions = [
        {
            "name": "sqlite_schema",
            "arguments": {"db_path": db_path},
            "rationale": "Inspect the existing database schema before changing state.",
        },
        {
            "name": "sqlite_exec",
            "arguments": {
                "db_path": db_path,
                "sql": (
                    "DROP TABLE IF EXISTS customer_revenue;"
                    "CREATE TABLE customer_revenue AS "
                    "SELECT customer_id, ROUND(SUM(quantity * unit_price), 2) AS total_revenue "
                    "FROM raw_orders WHERE status = 'paid' GROUP BY customer_id;"
                    "CREATE INDEX idx_customer_revenue_customer_id "
                    "ON customer_revenue(customer_id);"
                ),
            },
            "rationale": "Materialize the requested paid-order aggregate and create the required lookup index.",
        },
        {
            "name": "sqlite_query",
            "arguments": {
                "db_path": db_path,
                "sql": "SELECT customer_id, total_revenue FROM customer_revenue ORDER BY customer_id",
            },
            "rationale": "Query the final table in deterministic order to verify the state before answering.",
        },
    ]

    steps = []
    for index, action in enumerate(actions):
        started = time.time()
        observation = call_sqlite_tool(action["name"], action["arguments"])
        steps.append(
            {
                "index": index,
                "rationale": action["rationale"],
                "tool_call": action,
                "observation": observation,
                "latency_ms": int((time.time() - started) * 1000),
            }
        )
        if not observation.get("ok"):
            break
    return steps


def build_training_messages(prompt: str, steps: list[dict[str, Any]], final_answer: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "You are a software agent operating in SoftArena. Use the available tools to update "
                "the environment state. Provide concise, auditable rationales for tool choices."
            ),
        },
        {"role": "user", "content": prompt},
    ]
    for step in steps:
        call = step["tool_call"]
        messages.append(
            {
                "role": "assistant",
                "content": step["rationale"],
                "tool_calls": [
                    {
                        "name": call["name"],
                        "arguments": call["arguments"],
                    }
                ],
            }
        )
        messages.append(
            {
                "role": "tool",
                "name": call["name"],
                "content": step["observation"],
            }
        )
    messages.append({"role": "assistant", "content": final_answer})
    return messages
