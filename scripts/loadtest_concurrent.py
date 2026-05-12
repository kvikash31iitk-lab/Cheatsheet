"""Fire N concurrent /api/generate requests and report timings.

Run on the VPS as botuser so it can read .env for the internal token:

    sudo -u botuser bash -c 'cd /opt/video-notes-bot && \
        .venv/bin/python scripts/loadtest_concurrent.py \
        --user-id <admin-user-id> --n 5'

Find your user-id via /admin/users (it's in the URL of your detail page),
or query: SELECT id, email FROM users WHERE is_admin = true;

The script:
  1. Submits N POST /api/generate requests in parallel for the same short test
     video (19-second "Me at the zoo").
  2. Polls each job status every 2 seconds until done/error.
  3. Prints a timing table: when each was submitted, when each finished,
     queue-wait, and active-processing time.

NOTE: the test user must have enough free quota or `bypass_paid` set to True
(via /admin/users/[id]) so all N jobs are accepted. Otherwise the 4th/5th
will be rejected with 402 since free tier is 3 cheats + 1 book / day.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

import httpx

try:
    from dotenv import load_dotenv  # type: ignore
except ImportError:
    load_dotenv = None  # type: ignore

# Default test URL — "Me at the zoo", 19 seconds, the oldest YouTube video.
DEFAULT_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
API_BASE = "http://127.0.0.1:8000"


async def submit(client: httpx.AsyncClient, idx: int, url: str, kind: str) -> dict:
    """POST /api/generate, return {idx, job_id, submit_ms, error}."""
    t0 = time.time()
    try:
        r = await client.post(
            f"{API_BASE}/api/generate",
            json={"url": url, "kind": kind},
            timeout=30.0,
        )
        elapsed = (time.time() - t0) * 1000
        if r.status_code != 200:
            return {
                "idx": idx,
                "job_id": None,
                "submit_ms": elapsed,
                "error": f"{r.status_code}: {r.text[:200]}",
            }
        return {
            "idx": idx,
            "job_id": r.json()["id"],
            "submit_ms": elapsed,
            "error": None,
        }
    except Exception as exc:
        return {
            "idx": idx,
            "job_id": None,
            "submit_ms": (time.time() - t0) * 1000,
            "error": str(exc),
        }


async def watch(client: httpx.AsyncClient, info: dict, t_start: float) -> dict:
    """Poll a single job until terminal state. Returns enriched info with
    timing breakdown: first time we observed `running`, and final done/error."""
    if not info["job_id"]:
        return {**info, "first_running_at": None, "done_at": None, "final_state": "rejected"}

    first_running = None
    while True:
        await asyncio.sleep(2)
        try:
            r = await client.get(f"{API_BASE}/api/jobs/{info['job_id']}", timeout=15.0)
            r.raise_for_status()
            status = r.json().get("status", {})
            state = status.get("state")
        except Exception as exc:
            return {
                **info,
                "first_running_at": first_running,
                "done_at": time.time() - t_start,
                "final_state": f"poll-error: {exc}",
            }

        if state == "running" and first_running is None:
            first_running = time.time() - t_start

        if state in ("done", "error"):
            return {
                **info,
                "first_running_at": first_running,
                "done_at": time.time() - t_start,
                "final_state": state,
                "step_at_end": status.get("step", ""),
            }


async def main(args) -> None:
    # Load .env so INTERNAL_API_TOKEN is available.
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if load_dotenv and env_path.exists():
        load_dotenv(env_path)

    token = os.environ.get("INTERNAL_API_TOKEN", "")
    if not token:
        print("ERROR: INTERNAL_API_TOKEN not in env. Did you run as botuser?")
        sys.exit(1)

    headers = {"X-User-ID": args.user_id, "X-Internal-Token": token}

    print(f"\n=== Load test ===")
    print(f"  base:     {API_BASE}")
    print(f"  user:     {args.user_id}")
    print(f"  url:      {args.url}")
    print(f"  kind:     {args.kind}")
    print(f"  N:        {args.n}")
    print()

    async with httpx.AsyncClient(headers=headers) as client:
        # Fire N submissions in parallel.
        t_start = time.time()
        print(f"[{0.0:6.1f}s] Submitting {args.n} jobs in parallel...")
        submits = await asyncio.gather(
            *[submit(client, i, args.url, args.kind) for i in range(1, args.n + 1)]
        )

        for s in submits:
            err = f" ERROR: {s['error']}" if s["error"] else ""
            print(
                f"[{(time.time()-t_start):6.1f}s] Job #{s['idx']:>2} submitted "
                f"in {s['submit_ms']:>6.0f} ms · id={s['job_id'] or '—'}{err}"
            )

        accepted = [s for s in submits if s["job_id"]]
        if not accepted:
            print("\nAll submissions were rejected. Check the errors above.")
            return

        print(f"\n[{(time.time()-t_start):6.1f}s] Watching {len(accepted)} jobs...")
        results = await asyncio.gather(
            *[watch(client, s, t_start) for s in accepted]
        )

    # Print final table.
    print("\n" + "=" * 86)
    print(f"{'Job':>3}  {'Submit→Run':>11}  {'Total':>8}  {'Active':>8}  {'State':<9}  Note")
    print("-" * 86)
    for r in sorted(results, key=lambda r: r["idx"]):
        if not r["job_id"]:
            print(f"{r['idx']:>3}  {'—':>11}  {'—':>8}  {'—':>8}  {'rejected':<9}  {r['error']}")
            continue
        wait = r["first_running_at"]
        done = r["done_at"] or 0
        active = (done - wait) if wait is not None else None
        wait_s = f"{wait:>6.1f}s" if wait is not None else "—"
        active_s = f"{active:>6.1f}s" if active is not None else "—"
        print(
            f"{r['idx']:>3}  {wait_s:>11}  {done:>6.1f}s  {active_s:>8}  "
            f"{r['final_state']:<9}  {r.get('step_at_end','')[:30]}"
        )
    print("=" * 86)
    print(f"\nWall-clock total: {time.time() - t_start:.1f}s")
    print("Submit→Run = how long until the job started executing (queue wait)")
    print("Active     = actual pipeline runtime once it started")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--user-id", required=True, help="User ID to attribute jobs to")
    p.add_argument("--n", type=int, default=5, help="Number of concurrent jobs")
    p.add_argument("--url", default=DEFAULT_URL, help="YouTube URL to use")
    p.add_argument("--kind", default="cheatsheet", choices=["cheatsheet", "book"])
    asyncio.run(main(p.parse_args()))
