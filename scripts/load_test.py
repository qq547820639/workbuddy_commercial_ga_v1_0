#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import statistics
import time

import httpx


async def run_one(client: httpx.AsyncClient, path: str, headers: dict[str, str]) -> tuple[int, float]:
    started = time.perf_counter()
    response = await client.get(path, headers=headers)
    return response.status_code, (time.perf_counter() - started) * 1000


async def main_async(args) -> None:
    headers = {}
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"
    else:
        headers.update({"X-Tenant-ID": args.tenant, "X-Actor-ID": "load-test"})
    limits = httpx.Limits(max_connections=args.concurrency, max_keepalive_connections=args.concurrency)
    async with httpx.AsyncClient(base_url=args.base, timeout=args.timeout, limits=limits) as client:
        semaphore = asyncio.Semaphore(args.concurrency)
        async def guarded():
            async with semaphore:
                return await run_one(client, args.path, headers)
        results = await asyncio.gather(*(guarded() for _ in range(args.requests)))
    codes = [x[0] for x in results]; latency = sorted(x[1] for x in results)
    percentile = lambda p: latency[min(len(latency)-1, int(len(latency)*p))]
    print({
        "requests": len(results), "success": sum(200 <= x < 300 for x in codes),
        "errors": sum(not 200 <= x < 300 for x in codes),
        "latency_ms": {"mean": round(statistics.mean(latency), 2), "p50": round(percentile(.50), 2), "p95": round(percentile(.95), 2), "p99": round(percentile(.99), 2)},
    })
    if any(not 200 <= x < 300 for x in codes):
        raise SystemExit(2)


def main() -> None:
    p = argparse.ArgumentParser(description="Small dependency-free HTTP load probe for staging.")
    p.add_argument("--base", default="http://localhost:8000")
    p.add_argument("--path", default="/v1/dashboard")
    p.add_argument("--requests", type=int, default=200)
    p.add_argument("--concurrency", type=int, default=20)
    p.add_argument("--timeout", type=float, default=10)
    p.add_argument("--token", default="")
    p.add_argument("--tenant", default="00000000-0000-0000-0000-000000000001")
    asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    main()
