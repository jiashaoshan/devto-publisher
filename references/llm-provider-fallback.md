# LLM Provider 回退机制

> 最后的更新: 2026-05-26

## 问题背景

`scripts/devto_llm.py` 原本硬编码使用 `baiduqianfancodingplan` provider。实际使用中发现该 provider 存在严重的稳定性和兼容性问题：

- **baiduqianfancodingplan**: 频繁 429 限流；其 Coding Plan API 只支持 `qianfan-code-latest` 模型，`glm-5.1`/`deepseek-v4-flash` 等模型虽然出现在 openclaw 配置列表中但 API 返回 403
- **volcengine-plan**: 账户无 CodingPlan 订阅，所有 coding 端点返回 400

## 解决方案

### `get_provider_config()` 动态检测逻辑

1. 读取 Hermes 配置 (`~/.hermes/config.yaml`) 获取当前模型和供应商
2. 在 openclaw.json 的 `stable_order` 列表中寻找匹配当前模型的 provider
3. 若当前模型不匹配任何已知稳定 provider，使用第一个可用稳定 provider
3. 当前稳定列表（按优先级）: `volcengine-plan` > `sensenova` > `deepseek`

### `get_model()` 名称解析

- 从 Hermes 获取的模型名 (e.g. `glm5.1`) 与 openclaw 中的模型名 (e.g. `glm-5.1`) 可能有连字号差异
- `_model_matches()` 函数做模糊匹配：去掉连字号后比较

## Provider 验证记录

| Provider | baseUrl | 可用模型 | 状态 |
|----------|---------|---------|------|
| sensenova | https://token.sensenova.cn/v1 | deepseek-v4-flash | ✅ 已验证可用 |
| deepseek | https://api.deepseek.com | deepseek-v4-flash | ✅ 预期可用（未测试） |
| baiduqianfancodingplan | https://qianfan.baidubce.com/v2/coding | qianfan-code-latest | ⚠️ 限流频繁，仅 qianfan-code-latest 可用 |
| volcengine-plan | https://ark.cn-beijing.volces.com/api/coding/v3 | ark-code-latest | ✅ 新 key 已验证可用 |
| omlx | http://100.111.235.91:8000/v1 | gpt-oss-20b-MXFP4-Q8 | ❓ 内网环境 |

## 维护指南

当添加新 provider 时：

1. 先验证：用 `curl` 或 Python 测试 chat/completions 端点
2. 将验证通过的 provider 加入 `stable_order` 列表
3. 记录模型名和状态到上表
4. 注意区分 "Coding Plan" 端点 vs 通用 LLM 端点（URL 路径不同）