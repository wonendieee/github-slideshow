#!/usr/bin/env python3
"""Generate structured 5-year company intelligence markdown reports from QCC MCP endpoints."""

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

UNAVAILABLE = "无法获取（接口未返回或权限不足）"


@dataclass
class EndpointResult:
    endpoint: str
    total_records: int
    filtered_records: int
    payload: Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate structured company report markdown from QCC MCP APIs")
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
    for pattern in DATE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        raw = match.group(0).replace("年", "-").replace("月", "-").replace("日", "")
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
        dates = [extract_date(v) for v in item.values() if not isinstance(v, (dict, list))]
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
        filtered_obj: dict[str, Any] = {}
        total = 0
        kept = 0
        for key, value in payload.items():
            if isinstance(value, list):
                new_value = [x for x in value if within_years(x, cutoff)]
                total += len(value)
                kept += len(new_value)
                filtered_obj[key] = new_value
            else:
                filtered_obj[key] = value
        return filtered_obj, total, kept
    return payload, 1, 1


def query_endpoint(server_url: str, token: str, company: str, timeout: int) -> Any:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {"companyName": company, "keyword": company}
    response = requests.post(server_url, headers=headers, json=body, timeout=timeout)
    response.raise_for_status()
    try:
        return response.json()
    except Exception:
        return {"raw": response.text}


def flatten_records(data: Any, path: str = "") -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    if isinstance(data, dict):
        for key, value in data.items():
            p = f"{path}.{key}" if path else key
            out.extend(flatten_records(value, p))
    elif isinstance(data, list):
        for idx, value in enumerate(data):
            p = f"{path}[{idx}]"
            out.extend(flatten_records(value, p))
    else:
        out.append((path, data))
    return out


def find_values_by_keywords(data: Any, keywords: list[str], limit: int = 10) -> list[str]:
    result: list[str] = []
    lower_keywords = [k.lower() for k in keywords]
    for path, value in flatten_records(data):
        path_low = path.lower()
        if any(k in path_low for k in lower_keywords):
            text = str(value).strip()
            if text:
                result.append(f"`{path}`: {text}")
        if len(result) >= limit:
            break
    return result


def pick_or_unavailable(values: list[str]) -> list[str]:
    return values if values else [UNAVAILABLE]


def extract_sections(results_map: dict[str, Any]) -> dict[str, list[str]]:
    merged = {"all": results_map}

    sections = {
        "法人": pick_or_unavailable(find_values_by_keywords(merged, ["法人", "法定代表", "legal", "representative"])),
        "出资人": pick_or_unavailable(find_values_by_keywords(merged, ["出资", "investor", "认缴", "实缴"])),
        "注册资本": pick_or_unavailable(find_values_by_keywords(merged, ["注册资本", "capital", "regcap"])),
        "员工": pick_or_unavailable(find_values_by_keywords(merged, ["员工", "人员", "staff", "employee"])),
        "成立日期": pick_or_unavailable(find_values_by_keywords(merged, ["成立", "成立日期", "establish", "found"])),
        "工商信息": pick_or_unavailable(find_values_by_keywords(merged, ["工商", "登记", "信用代码", "注册号", "business", "license"])),
        "对外投资情况": pick_or_unavailable(find_values_by_keywords(merged, ["对外投资", "invest", "投资企业", "被投资"])),
        "股东信息": pick_or_unavailable(find_values_by_keywords(merged, ["股东", "shareholder", "持股", "股权"])),
        "社保情况": pick_or_unavailable(find_values_by_keywords(merged, ["社保", "保险", "social", "security"])),
        "股权关联信息": pick_or_unavailable(find_values_by_keywords(merged, ["股权", "控制", "穿透", "beneficial", "ownership"])),
        "集团风险提示": pick_or_unavailable(find_values_by_keywords(merged, ["风险", "异常", "处罚", "失信", "执行", "冻结"])),
        "股权穿透图": [UNAVAILABLE],
        "股权结构图": [UNAVAILABLE],
        "法律诉讼情况（全部）": pick_or_unavailable(find_values_by_keywords(merged, ["诉讼", "法院", "判决", "开庭", "案件", "legalcase"], limit=30)),
        "经营风险（全部）": pick_or_unavailable(find_values_by_keywords(merged, ["经营风险", "行政处罚", "欠税", "环保", "risk"], limit=30)),
        "资质证书": pick_or_unavailable(find_values_by_keywords(merged, ["资质", "证书", "cert"])),
        "纳税人资质": pick_or_unavailable(find_values_by_keywords(merged, ["纳税", "一般纳税人", "taxpayer", "tax"])),
        "招投标信息": pick_or_unavailable(find_values_by_keywords(merged, ["招投标", "中标", "投标", "bid", "tender"])),
        "行政许可": pick_or_unavailable(find_values_by_keywords(merged, ["行政许可", "许可", "permit", "license"])),
    }
    return sections


def render_bullet_section(lines: list[str], title: str, items: list[str]) -> None:
    lines.append(f"### {title}")
    for item in items:
        lines.append(f"- {item}")
    lines.append("")


def to_markdown(company: str, results: Iterable[EndpointResult], cutoff: dt.date) -> str:
    results_list = list(results)
    results_map = {r.endpoint: r.payload for r in results_list}
    sections = extract_sections(results_map)

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
    for result in results_list:
        lines.append(f"| {result.endpoint} | {result.total_records} | {result.filtered_records} |")

    lines.extend(["", "## 一、股权关联信息", ""])
    render_bullet_section(lines, "股权关联信息", sections["股权关联信息"])

    lines.extend(["## 二、基本信息", ""])
    for key in ["法人", "出资人", "注册资本", "员工", "成立日期", "工商信息", "对外投资情况", "股东信息", "社保情况"]:
        render_bullet_section(lines, key, sections[key])

    lines.extend(["## 三、集团风险提示", ""])
    render_bullet_section(lines, "集团风险提示", sections["集团风险提示"])

    lines.extend(["## 四、图谱信息", ""])
    render_bullet_section(lines, "股权穿透图", sections["股权穿透图"])
    render_bullet_section(lines, "股权结构图", sections["股权结构图"])

    lines.extend(["## 五、法律诉讼情况（全部）", ""])
    render_bullet_section(lines, "法律诉讼情况（全部）", sections["法律诉讼情况（全部）"])

    lines.extend(["## 六、经营风险（全部）", ""])
    render_bullet_section(lines, "经营风险（全部）", sections["经营风险（全部）"])

    lines.extend(["## 七、经营信息", ""])
    for key in ["资质证书", "纳税人资质", "招投标信息", "行政许可"]:
        render_bullet_section(lines, key, sections[key])

    lines.extend(["## 八、原始接口数据（近五年过滤后）", ""])
    for result in results_list:
        lines.extend([
            f"### {result.endpoint}",
            "```json",
            json.dumps(result.payload, ensure_ascii=False, indent=2),
            "```",
            "",
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

        markdown = to_markdown(company, results, cutoff)
        filename = re.sub(r"[^\w\-\u4e00-\u9fff]+", "_", company).strip("_")
        path = output_dir / f"{filename}_5y_report.md"
        path.write_text(markdown, encoding="utf-8")
        print(f"Generated: {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
