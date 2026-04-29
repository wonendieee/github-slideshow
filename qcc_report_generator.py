#!/usr/bin/env python3
"""Generate 5-year company intelligence markdown reports from QCC MCP endpoints."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import re
from dataclasses import dataclass
from typing import Any, Iterable

import requests

DEFAULT_SERVERS = {
    "qcc-company": "https://agent.qcc.com/mcp/company/stream",
    "qcc-risk": "https://agent.qcc.com/mcp/risk/stream",
    "qcc-ipr": "https://agent.qcc.com/mcp/ipr/stream",
    "qcc-operation": "https://agent.qcc.com/mcp/operation/stream",
    "qcc-executive": "https://agent.qcc.com/mcp/executive/stream",
}

DATE_PATTERNS = [
    re.compile(r"(19|20)\d{2}[-/.](0[1-9]|1[0-2])[-/.](0[1-9]|[12]\d|3[01])"),
    re.compile(r"(19|20)\d{2}年(0?[1-9]|1[0-2])月(0?[1-9]|[12]\d|3[01])日?"),
    re.compile(r"(19|20)\d{2}[-/.](0[1-9]|1[0-2])"),
]


@dataclass
class EndpointResult:
    endpoint: str
    total_records: int
    filtered_records: int
    payload: Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate company report markdown from QCC MCP APIs")
    parser.add_argument("companies", nargs="+", help="One or more company names")
    parser.add_argument("--token", default=os.getenv("QCC_BEARER_TOKEN"), help="QCC bearer token")
    parser.add_argument("--output-dir", default="reports", help="Directory for markdown reports")
    parser.add_argument("--lookback-years", type=int, default=5, help="How many years to keep")
    parser.add_argument("--timeout", type=int, default=30, help="Request timeout seconds")
    parser.add_argument(
        "--endpoints",
        nargs="*",
        default=list(DEFAULT_SERVERS.keys()),
        choices=list(DEFAULT_SERVERS.keys()),
        help="Subset of endpoints to query",
    )
    return parser.parse_args()


def extract_date(value: Any) -> dt.date | None:
    if value is None:
        return None
    text = str(value)
    for p in DATE_PATTERNS:
        m = p.search(text)
        if not m:
            continue
        raw = m.group(0)
        raw = raw.replace("年", "-").replace("月", "-").replace("日", "")
        raw = raw.replace("/", "-").replace(".", "-")
        if len(raw) == 7:
            raw = f"{raw}-01"
        try:
            return dt.date.fromisoformat(raw)
        except ValueError:
            continue
    return None


def within_years(item: Any, cutoff: dt.date) -> bool:
    if isinstance(item, dict):
        dates = [extract_date(v) for v in item.values()]
        dates = [d for d in dates if d is not None]
        if dates:
            return max(dates) >= cutoff
        return any(within_years(v, cutoff) for v in item.values())
    if isinstance(item, list):
        return any(within_years(v, cutoff) for v in item)
    parsed = extract_date(item)
    return parsed is None or parsed >= cutoff


def filter_payload(payload: Any, cutoff: dt.date) -> tuple[Any, int, int]:
    if isinstance(payload, list):
        filtered = [x for x in payload if within_years(x, cutoff)]
        return filtered, len(payload), len(filtered)
    if isinstance(payload, dict):
        filtered_obj = {}
        total = 0
        kept = 0
        for k, v in payload.items():
            if isinstance(v, list):
                new_v = [x for x in v if within_years(x, cutoff)]
                total += len(v)
                kept += len(new_v)
                filtered_obj[k] = new_v
            else:
                filtered_obj[k] = v
        return filtered_obj, total, kept
    return payload, 1, 1


def query_endpoint(server_url: str, token: str, company: str, timeout: int) -> Any:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body = {
        "companyName": company,
        "keyword": company,
    }
    resp = requests.post(server_url, headers=headers, json=body, timeout=timeout)
    resp.raise_for_status()
    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text}


def to_markdown(company: str, results: Iterable[EndpointResult], cutoff: dt.date) -> str:
    lines = [
        f"# {company} 近五年企业情报汇总",
        "",
        f"- 生成时间（UTC）：{dt.datetime.utcnow().isoformat(timespec='seconds')}Z",
        f"- 时间窗口起始：{cutoff.isoformat()}",
        "",
        "## 数据覆盖概览",
        "",
        "| 模块 | 原始记录数 | 近五年记录数 |",
        "|---|---:|---:|",
    ]
    for r in results:
        lines.append(f"| {r.endpoint} | {r.total_records} | {r.filtered_records} |")

    for r in results:
        lines.extend([
            "",
            f"## {r.endpoint}",
            "",
            "```json",
            json.dumps(r.payload, ensure_ascii=False, indent=2),
            "```",
        ])
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    if not args.token:
        raise SystemExit("Missing token. Provide --token or set QCC_BEARER_TOKEN.")

    output_dir = pathlib.Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cutoff = dt.date.today() - dt.timedelta(days=365 * args.lookback_years)

    for company in args.companies:
        results: list[EndpointResult] = []
        for endpoint in args.endpoints:
            payload = query_endpoint(DEFAULT_SERVERS[endpoint], args.token, company, args.timeout)
            filtered_payload, total, kept = filter_payload(payload, cutoff)
            results.append(EndpointResult(endpoint, total, kept, filtered_payload))

        md = to_markdown(company, results, cutoff)
        filename = re.sub(r"[^\w\-\u4e00-\u9fff]+", "_", company).strip("_")
        path = output_dir / f"{filename}_5y_report.md"
        path.write_text(md, encoding="utf-8")
        print(f"Generated: {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
