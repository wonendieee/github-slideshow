# 企查查近五年企业情报采集脚本

这个仓库新增了 `qcc_report_generator.py`，用于输入一个或多个公司名称，调用你有权限的企查查接口，并输出统一的 Markdown 报告，供后续大模型分析。

## 1) 准备

1. 安装依赖：

```bash
pip install requests
```

2. 配置 Token（推荐环境变量方式）：

```bash
export QCC_BEARER_TOKEN='你的Bearer Token'
```

## 2) 运行示例

```bash
python qcc_report_generator.py "腾讯科技（深圳）有限公司" "阿里巴巴（中国）有限公司" --output-dir reports
```

执行后会在 `reports/` 下生成：

- `腾讯科技_深圳_有限公司_5y_report.md`
- `阿里巴巴_中国_有限公司_5y_report.md`

## 3) 参数说明

- `companies`: 一个或多个公司名称（必填）
- `--token`: 企查查 Bearer Token（不传则读取 `QCC_BEARER_TOKEN`）
- `--output-dir`: 报告输出目录，默认 `reports`
- `--lookback-years`: 回溯年限，默认 `5`
- `--timeout`: 单次请求超时秒数，默认 `30`
- `--endpoints`: 只拉取指定模块，可选：
  - `qcc-company`
  - `qcc-risk`
  - `qcc-ipr`
  - `qcc-operation`
  - `qcc-executive`

示例（只拉风险与知识产权）：

```bash
python qcc_report_generator.py "京东科技控股股份有限公司" --endpoints qcc-risk qcc-ipr
```

## 4) 报告结构

每个公司生成一个 Markdown，包含：

1. 基本元信息（生成时间、时间窗口起始）
2. 各模块原始记录数与近五年记录数对比表
3. 各模块筛选后的 JSON 内容（代码块形式）

## 5) 二次加工建议（给大模型）

后续可把 Markdown 作为上下文，让模型执行：

- 风险事件时间线提取
- 法务/经营异常聚类
- 高管与对外投资关系梳理
- 同行业公司横向对比

## 6) 注意事项

- 不同接口返回字段可能不一致，脚本使用“自动识别日期字段”的泛化方式进行近五年筛选。
- 如果某些字段没有日期，会尽可能保留，避免误删关键信息。
- 生产环境建议：增加重试、分页、限流、断点续跑、日志落库。
