---
name: devto-publisher
version: 1.0.0
license: MIT
description: dev.to 全栈运营技能。AI 英文文章生成+API发布 + 评论区获客(搜索→评分→LLM评论→BrowserWing发表)。
metadata:
  openclaw:
    emoji: "🌐"
    category: publishing
  clawdbot:
    emoji: "🌐"
    requires:
      bins: ["python3", "curl"]
    install:
      - pip3 install requests
---

# dev.to 全栈运营技能 v1.2

> **v1.2 修复 (2026-05-26)**: LLM 模块改为动态检测 Hermes 当前模型 + 稳定提供商兜底（`sensenova` → `deepseek`），不再硬编码 `baiduqianfancodingplan`（该 provider 频繁限流且模型兼容性差）。详见 `references/llm-provider-fallback.md`。

> **v1.1 修复 (2026-05-26)**: 修复 API Key 读取逻辑（新增 `~/.hermes/.env` 路径、公开 API 不强制要求 key）、修复 BrowserWing URL 硬编码、增加 ConnectionError 友好提示。详见 `references/devto-api-quirks.md`。

## 功能总览

| 功能 | 脚本 | 说明 |
|------|------|------|
| 📝 **文章生成+发布** | `devto-article-publisher.py` | LLM 生成英文技术文章 → 确认 → API 直发 dev.to |
| 💬 **评论区获客** | `devto_acquisition.py` | 搜索 → AI 评分筛选 → LLM 评论 → BrowserWing 自动发表 |

---

## 快速开始

### 前置条件

1. **dev.to API Key**: 从 [dev.to/settings/account](https://dev.to/settings/account) 生成
2. **BrowserWing**: 运行在 `http://127.0.0.1:8080`（评论功能需要）
3. **LLM 模型**: 自动读取 Hermes 当前模型配置 → 在 openclaw.json 中匹配可用 provider（稳定兜底: `sensenova` → `deepseek`）

### 配置

```bash
# 1. 编辑 .env，填入你的 API Key
DEVTO_API_KEY=你的dev.to API Key
```

### 文章发布

```bash
# 测试（只生成不发布）
python3 scripts/devto-article-publisher.py --product-url "https://你的产品.com" --dry-run

# 自动发布
python3 scripts/devto-article-publisher.py --product-url "https://你的产品.com" --auto-confirm
```

### 评论区获客

```bash
# 搜索文章
python3 scripts/devto_acquisition.py search --keyword "AI API"

# 全自动获客
python3 scripts/devto_acquisition.py auto --product-url "https://你的产品.com" --max-comments 3

# 查看评论历史
python3 scripts/devto_acquisition.py history
```

---

## 设计架构

```
Product URL
    │
    ├──→ [文章发布] LLM 生成 → 草稿 → 确认 → POST /api/articles → dev.to
    │
    └──→ [评论区] LLM 生成关键词 → 搜索 → 评分筛选
         → ThreadPool(5) 并发生成评论
         → BrowserWing 串行发表 (间隔60-180s防封)
```

## 关键设计决策

| 决策 | 选择 | 原因 |
|------|------|------|
| 评论发表方式 | BrowserWing | dev.to API 不支持创建评论 |
| LLM 模型提供商 | 动态检测 → 稳定兜底 `sensenova`/`deepseek` | `baiduqianfancodingplan` 频繁限流、`volcengine-plan` 无 CodingPlan 订阅 |
| 评论生成 | ThreadPool 并发 | 节省 70% 时间 |
| 评论发表 | 串行 + 随机间隔 | 避免触发风控 |
| 文章风格 | 经验分享 | dev.to 开发者讨厌硬广 |

## 文件结构

```
devto-publisher/
├── SKILL.md                       # 技能描述
├── README.md                      # 完整文档
├── _meta.json                     # 元数据
├── .env                           # API Key
├── .devto_cookie                  # 登录 Cookie
├── .gitignore
├── bw-scripts/
│   ├── devto-comment.json         # BrowserWing 脚本备份
│   └── devto-comment.md          # 脚本说明
├── scripts/
│   ├── devto-article-publisher.py # 文章发布
│   ├── devto_acquisition.py       # 评论区获客
│   └── devto_llm.py              # LLM 调用
├── templates/
│   ├── article-prompt.md          # 文章生成模板
│   └── comment-strategic.md       # 评论生成模板
└── data/                          # 数据存储
```

## API 参考

| 操作 | 方式 | 端点 |
|------|------|------|
| 创建文章 | API | `POST /api/articles` (API Key) |
| 搜索文章 | API | `GET /api/articles?query=keyword` (公开) |
| 获取详情 | API | `GET /api/articles/:id` (公开) |
| 发表评论 | BrowserWing | `POST /api/v1/scripts/xxx/play` |
