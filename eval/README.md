# Eval Harness

评测脚本，用于验证 llama.cpp HTTP 推理接口的响应质量与延迟。

## 使用方式

### 离线模式（仅校验 test case schema，无需启动服务）

```bash
python3 eval/run_cases.py --offline
```

### 在线模式（需要本地服务已启动）

```bash
# 先启动服务
./scripts/run_server.sh

# 然后运行评测
python3 eval/run_cases.py --server http://localhost:8080
```

## 输出报告

运行后在 `eval/` 目录下生成：

| 文件 | 格式 | 说明 |
|------|------|------|
| `report.json` | JSON | 结构化结果，含汇总与逐条明细 |
| `report.md`   | Markdown | 人类可读报告，含摘要表格 |

## 错误类型（Error Type Enum）

| 类型 | 触发条件 |
|------|---------|
| `runtime_error` | HTTP / 网络错误 |
| `timeout_error` | 请求超时 |
| `quality_error` | 服务正常响应，但未满足质量门控（长度、关键词等） |
| `config_error`  | test case 定义缺少必填字段 |

## 质量门控字段（`cases.json`）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | **必填** 用例标识 |
| `prompt` | string | **必填** 输入提示词 |
| `n_predict` | int | 最大生成 token 数（默认 128） |
| `temperature` | float | 温度参数（默认 0.0） |
| `timeout_s` | int | 超时秒数（默认 30） |
| `expect_min_len` | int | 响应文本最短字符数（质量门控） |
| `expect_contains` | list[str] | 响应必须包含的关键词列表（质量门控） |

## 报告 JSON 结构示例

```json
{
  "mode": "online",
  "summary": {
    "total": 3,
    "passed": 2,
    "failed": 1,
    "runtime_fail_count": 0,
    "quality_fail_count": 1,
    "config_fail_count": 0,
    "fail_type_counts": {
      "quality_error": 1
    }
  },
  "fail_types": {},
  "quality_fail_types": {
    "missing_term": 1
  },
  "cases": [
    {
      "id": "math_simple",
      "ok": false,
      "error_type": "quality_error",
      "reason": "missing_term",
      "error_message": "response missing expected term: '4'",
      "duration_ms": 312.5,
      "timings_ms": { "total_ms": 312.5 },
      "response_preview": "The answer is five."
    }
  ]
}
```

### 字段说明

| 顶层字段 | 说明 |
|----------|------|
| `fail_types` | 运行时/配置失败类型计数（`runtime_error` / `timeout_error` / `config_error`） |
| `quality_fail_types` | 质量门控失败原因计数（`response_too_short` / `missing_term`） |

每个 case 的 `reason` 字段：质量门控失败时填写具体原因码（如 `response_too_short`、`missing_term`），其他情况为 `null`。
