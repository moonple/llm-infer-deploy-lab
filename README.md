# LLM Inference Deployment Lab

> 个人学习 LLM 推理部署与服务化的实验仓库  
> 硬件：RTX 3060 6GB | 模型：Qwen2.5-3B-Instruct-Q4_K_M

## 项目目标
- 掌握 LLM 推理部署工程化能力
- 构建可观测、可扩展的推理服务
- 为求职积累可量化的项目经验

## 环境配置
- **系统**：Windows 11 + WSL2 (Ubuntu)
- **GPU**：NVIDIA RTX 3060 6GB
- **框架**：llama.cpp (CUDA)
- **模型**：Qwen2.5-3B-Instruct-Q4_K_M (GGUF)

## 基准测试结果

| 序号 | ctx | ngl | batch | tokens/s | TTFT(ms) | 模型显存(MB) | 总显存(MB) |
|------|-----|-----|-------|----------|----------|--------------|------------|
| 1 | 2048 | 20 | 256 | 22.77 | 354.23 | 1086.04 | 2512 |
| 2 | 2048 | 20 | 512 | 22.63 | 332.12 | 1086.04 | 2655 |
| 3 | 2048 | 35 | 256 | 70.22 | 208.37 | 1740.74 | 3192 |
| 4 | 2048 | 35 | 512 | 71.53 | 219.81 | 1740.74 | 3340 |
| 5 | 4096 | 20 | 256 | 22.49 | 322.84 | 1086.04 | 2540 |
| 6 | 4096 | 20 | 512 | 24.49 | 375.66 | 1086.04 | 2694 |
| 7 | 4096 | 35 | 256 | 70.58 | 233.85 | 1740.74 | 3205 |
| 8 | 4096 | 35 | 512 | 63.56 | 211.72 | 1740.74 | 3355 |

### 关键结论
- **GPU 层数是关键**：ngl=35 比 ngl=20 快 3 倍
- **最优配置**：ctx=4096, ngl=35, batch=256（速度 70+ tokens/s，显存 3.2GB）
- **6GB 显存可同时服务 2 个并发**（每个 slot 约 1.6GB）

## 快速启动

```bash
# 1. 进入目录
cd ~/llm-infer-deploy-lab

# 2. 启动服务（参考 llama.cpp 文档，例如）
# ./llama-server -m /path/to/model.gguf --port 8080

# 3. 测试 API（新开终端）
curl http://localhost:8080/completion \
    -H "Content-Type: application/json" \
    -d '{"prompt": "Hello", "n_predict": 50}'
```

## 评测 (Eval)

评测脚本支持两种模式：

```bash
# 离线模式（CI 默认，仅校验 test case schema）
python3 eval/run_cases.py --offline

# 在线模式（需要本地服务已启动）
python3 eval/run_cases.py --server http://localhost:8080
```

报告生成在 `eval/report.json` 和 `eval/report.md`，其中质量门控失败（`quality_fail_types` / `quality_error`）与运行时失败（`fail_types`：`runtime_error` / `timeout_error`）分开计数，每条用例包含 `reason` 字段说明具体失败原因。

详见 [eval/README.md](eval/README.md)。
