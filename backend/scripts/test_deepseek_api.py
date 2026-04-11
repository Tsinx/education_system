import argparse
import asyncio
import json
import os
import sys
import statistics
import time
from dataclasses import asdict, dataclass
from typing import Any

import httpx

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.core.config import settings


@dataclass
class RequestResult:
    index: int
    ok: bool
    status_code: int | None
    latency_s: float
    ttfb_s: float | None
    error: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    output_chars: int


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    sorted_vals = sorted(values)
    rank = (len(sorted_vals) - 1) * p
    low = int(rank)
    high = min(low + 1, len(sorted_vals) - 1)
    frac = rank - low
    return sorted_vals[low] * (1 - frac) + sorted_vals[high] * frac


async def run_one_request(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    model: str,
    prompt: str,
    temperature: float,
    max_tokens: int,
    stream: bool,
    index: int,
) -> RequestResult:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": stream,
    }
    t0 = time.monotonic()
    ttfb_s: float | None = None
    status_code: int | None = None
    prompt_tokens = None
    completion_tokens = None
    total_tokens = None
    output_text = ""
    try:
        if stream:
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                status_code = resp.status_code
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    content = line[6:]
                    if content.strip() == "[DONE]":
                        break
                    chunk = json.loads(content)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    piece = delta.get("content", "")
                    if piece:
                        output_text += piece
                        if ttfb_s is None:
                            ttfb_s = time.monotonic() - t0
                    usage = chunk.get("usage") or {}
                    prompt_tokens = usage.get("prompt_tokens", prompt_tokens)
                    completion_tokens = usage.get("completion_tokens", completion_tokens)
                    total_tokens = usage.get("total_tokens", total_tokens)
        else:
            resp = await client.post(url, headers=headers, json=payload)
            status_code = resp.status_code
            resp.raise_for_status()
            data = resp.json()
            output_text = data["choices"][0]["message"]["content"]
            ttfb_s = time.monotonic() - t0
            usage = data.get("usage") or {}
            prompt_tokens = usage.get("prompt_tokens")
            completion_tokens = usage.get("completion_tokens")
            total_tokens = usage.get("total_tokens")

        latency_s = time.monotonic() - t0
        return RequestResult(
            index=index,
            ok=bool(output_text),
            status_code=status_code,
            latency_s=latency_s,
            ttfb_s=ttfb_s,
            error=None if output_text else "empty_output",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            output_chars=len(output_text),
        )
    except Exception as exc:
        latency_s = time.monotonic() - t0
        return RequestResult(
            index=index,
            ok=False,
            status_code=status_code,
            latency_s=latency_s,
            ttfb_s=ttfb_s,
            error=str(exc),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            output_chars=len(output_text),
        )


async def benchmark(
    requests: int,
    concurrency: int,
    timeout_s: float,
    stream: bool,
    prompt: str,
    temperature: float,
    max_tokens: int,
) -> list[RequestResult]:
    base_url = settings.deepseek_base_url.rstrip("/")
    api_key = settings.deepseek_api_key.strip()
    model = settings.deepseek_model.strip()

    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY 未配置，无法测试。")
    if not base_url:
        raise RuntimeError("DEEPSEEK_BASE_URL 未配置，无法测试。")
    if not model:
        raise RuntimeError("DEEPSEEK_MODEL 未配置，无法测试。")

    url = f"{base_url}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    timeout = httpx.Timeout(timeout_s)
    limits = httpx.Limits(max_connections=concurrency * 2, max_keepalive_connections=concurrency)

    sem = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        async def worker(i: int) -> RequestResult:
            async with sem:
                return await run_one_request(
                    client=client,
                    url=url,
                    headers=headers,
                    model=model,
                    prompt=prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=stream,
                    index=i,
                )

        tasks = [asyncio.create_task(worker(i + 1)) for i in range(requests)]
        return await asyncio.gather(*tasks)


def print_report(
    results: list[RequestResult],
    elapsed_s: float,
    request_count: int,
    concurrency: int,
    stream: bool,
) -> dict[str, Any]:
    success = [r for r in results if r.ok]
    failed = [r for r in results if not r.ok]
    latencies = [r.latency_s for r in success]
    ttfbs = [r.ttfb_s for r in success if r.ttfb_s is not None]
    total_tokens = [r.total_tokens for r in success if r.total_tokens is not None]
    completion_tokens = [r.completion_tokens for r in success if r.completion_tokens is not None]
    output_chars = [r.output_chars for r in success]

    report = {
        "requests_total": request_count,
        "requests_success": len(success),
        "requests_failed": len(failed),
        "success_rate": len(success) / request_count if request_count else 0.0,
        "elapsed_s": elapsed_s,
        "throughput_req_s": request_count / elapsed_s if elapsed_s > 0 else 0.0,
        "latency_s": {
            "min": min(latencies) if latencies else None,
            "avg": statistics.fmean(latencies) if latencies else None,
            "p50": percentile(latencies, 0.50) if latencies else None,
            "p95": percentile(latencies, 0.95) if latencies else None,
            "max": max(latencies) if latencies else None,
        },
        "ttfb_s": {
            "min": min(ttfbs) if ttfbs else None,
            "avg": statistics.fmean(ttfbs) if ttfbs else None,
            "p50": percentile(ttfbs, 0.50) if ttfbs else None,
            "p95": percentile(ttfbs, 0.95) if ttfbs else None,
            "max": max(ttfbs) if ttfbs else None,
        },
        "tokens": {
            "total_avg": statistics.fmean(total_tokens) if total_tokens else None,
            "completion_avg": statistics.fmean(completion_tokens) if completion_tokens else None,
        },
        "output_chars_avg": statistics.fmean(output_chars) if output_chars else 0.0,
        "failed_samples": [
            {
                "index": r.index,
                "status_code": r.status_code,
                "error": r.error,
                "latency_s": r.latency_s,
            }
            for r in failed[:5]
        ],
        "mode": "stream" if stream else "non_stream",
        "concurrency": concurrency,
    }

    print("==== DeepSeek API Benchmark ====")
    print(f"mode            : {'stream' if stream else 'non-stream'}")
    print(f"concurrency     : {concurrency}")
    print(f"requests        : {request_count}")
    print(f"success/failed  : {len(success)}/{len(failed)}")
    print(f"success rate    : {report['success_rate']:.2%}")
    print(f"elapsed (s)     : {elapsed_s:.3f}")
    print(f"throughput rps  : {report['throughput_req_s']:.3f}")
    if latencies:
        print(
            "latency (s)     : "
            f"min={report['latency_s']['min']:.3f}, "
            f"avg={report['latency_s']['avg']:.3f}, "
            f"p50={report['latency_s']['p50']:.3f}, "
            f"p95={report['latency_s']['p95']:.3f}, "
            f"max={report['latency_s']['max']:.3f}"
        )
    if ttfbs:
        print(
            "ttfb (s)        : "
            f"min={report['ttfb_s']['min']:.3f}, "
            f"avg={report['ttfb_s']['avg']:.3f}, "
            f"p50={report['ttfb_s']['p50']:.3f}, "
            f"p95={report['ttfb_s']['p95']:.3f}, "
            f"max={report['ttfb_s']['max']:.3f}"
        )
    if report["tokens"]["total_avg"] is not None:
        print(
            "tokens avg      : "
            f"total={report['tokens']['total_avg']:.1f}, "
            f"completion={report['tokens']['completion_avg']:.1f}"
        )
    print(f"output chars avg: {report['output_chars_avg']:.1f}")
    if failed:
        print("failed samples  :")
        for item in report["failed_samples"]:
            print(
                f"  - #{item['index']} status={item['status_code']} "
                f"latency={item['latency_s']:.3f}s error={item['error']}"
            )

    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DeepSeek API 可用性与性能测试脚本")
    parser.add_argument("--requests", type=int, default=10, help="总请求数")
    parser.add_argument("--concurrency", type=int, default=3, help="并发数")
    parser.add_argument("--timeout", type=float, default=60.0, help="单请求超时（秒）")
    parser.add_argument("--stream", action="store_true", help="启用流式请求测试")
    parser.add_argument("--temperature", type=float, default=0.0, help="temperature")
    parser.add_argument("--max-tokens", type=int, default=64, help="max_tokens")
    parser.add_argument(
        "--prompt",
        type=str,
        default="请用一句话介绍重庆交通大学。",
        help="测试用提示词",
    )
    parser.add_argument("--output", type=str, default="", help="JSON 报告输出路径（可选）")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.requests <= 0:
        raise ValueError("--requests 必须大于 0")
    if args.concurrency <= 0:
        raise ValueError("--concurrency 必须大于 0")
    if args.concurrency > args.requests:
        args.concurrency = args.requests

    print("starting benchmark ...")
    t0 = time.monotonic()
    results = asyncio.run(
        benchmark(
            requests=args.requests,
            concurrency=args.concurrency,
            timeout_s=args.timeout,
            stream=args.stream,
            prompt=args.prompt,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
        )
    )
    elapsed_s = time.monotonic() - t0
    report = print_report(
        results=results,
        elapsed_s=elapsed_s,
        request_count=args.requests,
        concurrency=args.concurrency,
        stream=args.stream,
    )
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "report": report,
                    "results": [asdict(r) for r in results],
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        print(f"json report saved: {args.output}")


if __name__ == "__main__":
    main()
