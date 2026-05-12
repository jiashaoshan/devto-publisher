# devto-publisher

🌐 dev.to 全栈运营技能 — AI 文章生成+发布 + 评论区获客

---

## 功能总览

| 功能 | 说明 | 方式 |
|------|------|------|
| 📝 **文章生成+发布** | LLM 生成英文技术文章 → 确认 → 通过 API 发布到 dev.to | REST API |
| 💬 **评论区获客** | 搜索 → AI 评分筛选 → LLM 生成评论 → BrowserWing 自动发表 | BrowserWing |

---

## 设计理念

dev.to 是一个全球开发者社区，每月活跃用户超过 1500 万。本技能的目标是通过**有价值的技术内容**在 dev.to 上建立影响力，并自然地引流到自己的产品。

### 核心原则

- **内容优先**：每篇文章必须提供真实的开发者价值，去掉产品推广仍然是 90% 有用的文章
- **自然互动**：评论要像真实开发者交流，不硬广、不推销
- **并发高效**：LLM 评论生成并行化，节省等待时间
- **安全防封**：评论发表串行 + 随机间隔 60-180s

---

## 架构设计

```
┌─────────────────────────────────────────────────────┐
│                    用户输入                          │
│            --product-url "https://..."              │
└──────────────────┬──────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────┐
│                    LLM 模块                           │
│          (devto_llm.py - baiduqianfancodingplan)     │
│   从 openclaw.json 自动读取 API Key + Base URL       │
└─────────┬─────────────────────────────┬──────────────┘
          │                             │
          ▼                             ▼
┌──────────────────┐    ┌──────────────────────────────┐
│  文章发布模块     │    │    评论区获客模块              │
│  article-        │    │    devto_acquisition.py       │
│  publisher.py    │    │                              │
│                  │    │  1. LLM 生成搜索关键词         │
│  1. 读取模板     │    │  2. 搜索 dev.to 文章           │
│  2. LLM 生成     │    │  3. 规则评分(热度+互动+时效)   │
│  3. 保存草稿     │    │  4. 并发获取详情+生成评论      │
│  4. 确认发布     │    │     (ThreadPool 5线程)         │
│  5. API 直发     │    │  5. BrowserWing 串行发表       │
│  6. 记录历史     │    │  6. 记录历史                   │
└──────────────────┘    └──────────────────────────────┘
```

### 数据流

```
文章发布:
  Product URL → LLM(模板) → .md草稿 → 人工确认 → POST /api/articles → dev.to

评论区获客:
  Product URL → LLM生成关键词 → GET /api/articles?query=KW
  → 规则评分 → 筛选Top N
  → ThreadPool: GET /api/articles/:id + LLM生成评论 (并发)
  → BrowserWing: POST /scripts/xxx/play (串行, 间隔60-180s)
```

---

## 文件结构

```
devto-publisher/
├── SKILL.md                       # OpenClaw 技能描述
├── README.md                      # 本文档
├── _meta.json                     # 技能元数据
├── .env                           # API Key 配置
├── .gitignore                     # Git 忽略规则
├── .devto_cookie                  # dev.to 登录 Cookie
├── scripts/
│   ├── devto-article-publisher.py # 文章生成+发布
│   ├── devto_acquisition.py       # 评论区获客
│   └── devto_llm.py               # LLM 调用模块
├── templates/
│   ├── article-prompt.md          # 文章生成模板
│   └── comment-strategic.md       # 评论生成模板
└── data/                          # 草稿/发布历史/评论历史
```

---

## 安装

### 前置依赖

- Python 3.9+
- `requests` 库
- OpenClaw Gateway（运行中，提供 LLM 配置）
- BrowserWing 服务（http://127.0.0.1:8080，评论区获客需要）
- dev.to 账号 + BrowserWing 脚本（评论区获客需要）

### 安装步骤

```bash
# 1. 克隆仓库
git clone https://github.com/jiashaoshan/devto-publisher.git
cd devto-publisher

# 2. 安装 Python 依赖
pip3 install requests

# 3. 配置 API Key
# 编辑 .env 文件
echo "DEVTO_API_KEY=你的dev.to API Key" > .env

# 4. LLM 自动从 openclaw.json 读取 baiduqianfancodingplan 配置
# 无需额外配置
```

### API Key 获取

1. 打开 https://dev.to/settings/account
2. 找到 **API Keys** 区域
3. 点击 **Generate API Key**
4. 复制生成的 Key，填入 `.env` 文件

---

## 使用指南

### 文章发布

```bash
# 测试模式（只生成文章，不发布）
python3 scripts/devto-article-publisher.py \
  --product-url "https://你的产品.com" \
  --dry-run

# 交互确认发布
python3 scripts/devto-article-publisher.py \
  --product-url "https://你的产品.com"

# 自动发布（非交互）
python3 scripts/devto-article-publisher.py \
  --product-url "https://你的产品.com" \
  --auto-confirm

# 发布为草稿（不公开）
python3 scripts/devto-article-publisher.py \
  --product-url "https://你的产品.com" \
  --auto-confirm \
  --publish-as-draft
```

### 评论区获客

```bash
# 搜索文章（查看评分排序）
python3 scripts/devto_acquisition.py search --keyword "AI API"

# 全自动获客（发表真实评论）
python3 scripts/devto_acquisition.py auto \
  --product-url "https://你的产品.com" \
  --max-comments 5

# 测试模式（跑流程但不发评论）
python3 scripts/devto_acquisition.py auto \
  --product-url "https://你的产品.com" \
  --max-comments 3 \
  --dry-run

# 评论指定文章
python3 scripts/devto_acquisition.py comment \
  --article-url "https://dev.to/username/article-slug"

# 查看评论历史
python3 scripts/devto_acquisition.py history
```

---

## 配置说明

### LLM 模型

本技能使用 **百度千帆 Coding Plan**（`baiduqianfancodingplan/qianfan-code-latest`），配置自动从 `~/.openclaw/openclaw.json` 读取：

```json
{
  "baiduqianfancodingplan": {
    "baseUrl": "https://qianfan.baidubce.com/v2/coding",
    "apiKey": "bce-v3/...",
    "api": "openai-completions",
    "models": [{"id": "qianfan-code-latest"}]
  }
}
```

### dev.to API

| 端点 | 方法 | 用途 | 认证 |
|------|------|------|------|
| `/api/articles` | GET | 搜索/列表文章 | 公开 |
| `/api/articles/:id` | GET | 获取文章详情 | 公开 |
| `/api/articles` | POST | 创建文章 | API Key |
| `/api/articles/:id` | PUT | 更新文章 | API Key |
| `/api/comments?a_id=:id` | GET | 读取评论 | 公开 |
| `/api/comments` | POST | ❌ 不支持 | API Key |

### 浏览器脚本

评论区发表使用 BrowserWing 自动化脚本（已录制）：
- 脚本 ID: `8fda52e1-f197-4ed5-8ee6-8dec3d555a74`
- 参数: `{ "内容": "...", "链接": "..." }`
- 需要 dev.to 登录 Cookie（已保存在 `.devto_cookie`）

---

## 依赖关系

```
devto-publisher
├── Python 3.9+ (运行环境)
├── requests (HTTP 客户端)
├── OpenClaw Gateway (LLM 模型配置)
│   └── baiduqianfancodingplan (LLM 提供者)
├── BrowserWing (浏览器自动化，评论发表用)
│   └── http://127.0.0.1:8080
└── dev.to (目标平台)
    ├── API Key (文章发布)
    └── 登录 Cookie (评论发表)
```

---

## 常见问题

### Q: 文章提示词太广告化了怎么办？
模板已改为"经验分享"风格。如果还需要调整，编辑 `templates/article-prompt.md`。

### Q: 评论发表失败？
1. 检查 BrowserWing 是否运行：`curl http://127.0.0.1:8080/api/v1/scripts`
2. 检查 dev.to Cookie 是否过期：重新登录后更新 `.devto_cookie`
3. 检查网络连接

### Q: LLM 调用报错？
1. 确认 openclaw.json 中 baiduqianfancodingplan 配置正确
2. 检查百度千帆 API Key 是否有效（每日抢购模型，注意配额）

### Q: 如何更新 Cookie？
重新登录 dev.to，从浏览器开发者工具中复制 Cookie 字符串，写入 `.devto_cookie` 文件。

---

## License

MIT
