#!/usr/bin/env python3
"""
dev.to 文章发布模块
功能：
  1. 读取 article-prompt.md 模板
  2. 调用 LLM 根据产品链接生成技术文章（英文）
  3. 人工确认流程
  4. 通过 dev.to REST API 直接发布
  5. 记录发布历史到 data/published-articles.json

差异（对比 juejin-publisher）：
  - dev.to 有干净的 REST API，无需 BrowserWing/浏览器自动化
  - 使用 API Key 认证，无需 Cookie
  - 文章是英文，面向全球开发者
"""

import argparse
import json
import logging
import os
import sys
import time
import requests
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List

# ─── 模块路径 ─────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent.absolute()
SKILL_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

# 导入 dev.to 专用 LLM 模块（使用 openclaw 配置的 baiduqianfancodingplan）
sys.path.insert(0, str(SCRIPT_DIR))
from devto_llm import call_llm_json, call_llm

logger = logging.getLogger(__name__)

# ─── 路径定义 ─────────────────────────────────────────────
TEMPLATES_DIR = SKILL_DIR / "templates"
DATA_DIR = SKILL_DIR / "data"
ARTICLE_PROMPT_FILE = TEMPLATES_DIR / "article-prompt.md"
PUBLISHED_FILE = DATA_DIR / "published-articles.json"

# ─── dev.to API 配置 ─────────────────────────────────────
DEVTO_API_BASE = "https://dev.to/api"

# 确保 data 目录存在
DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_env() -> Dict[str, str]:
    """加载 .env 配置文件"""
    env = {}
    env_file = SKILL_DIR / ".env"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    return env


def get_devto_api_key() -> str:
    """获取 dev.to API Key"""
    # 1. 环境变量优先
    key = os.environ.get("DEVTO_API_KEY", "")
    if key:
        return key
    # 2. .env 文件
    env = load_env()
    key = env.get("DEVTO_API_KEY", "")
    if key:
        return key
    # 3. openclaw 全局配置
    try:
        import json
        oc_path = os.path.expanduser("~/.openclaw/openclaw.json")
        with open(oc_path) as f:
            oc = json.load(f)
        env_config = oc.get("env", {})
        if isinstance(env_config, dict):
            for k, v in env_config.items():
                if "devto" in k.lower() and "api" in k.lower():
                    if isinstance(v, str) and v.strip():
                        return v.strip()
    except Exception:
        pass
    raise ValueError("DEVTO_API_KEY 未配置，请在 .env 中设置或通过环境变量传入")


def read_prompt() -> str:
    """读取文章生成提示词模板"""
    if ARTICLE_PROMPT_FILE.exists():
        with open(ARTICLE_PROMPT_FILE, encoding="utf-8") as f:
            return f.read()
    logger.warning("article-prompt.md 未找到，使用默认提示词")
    return "Write a technical article for dev.to about the product. Be practical and developer-focused."


def load_published() -> List[Dict]:
    """加载已发布文章历史"""
    if PUBLISHED_FILE.exists():
        try:
            with open(PUBLISHED_FILE, encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return []
    return []


def save_published(articles: List[Dict]):
    """保存已发布文章历史"""
    with open(PUBLISHED_FILE, "w", encoding="utf-8") as f:
        json.dump(articles, f, indent=2, ensure_ascii=False)


def save_draft(title: str, body: str, tags: List[str]):
    """保存文章草稿到本地"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_title = "".join(c if c.isalnum() or c in " _-" else "_" for c in title)[:40]
    draft_file = DATA_DIR / f"devto_draft_{timestamp}_{safe_title}.md"
    content = f"""---
title: {title}
tags: {", ".join(tags)}
created: {datetime.now().isoformat()}
---

{body}
"""
    with open(draft_file, "w", encoding="utf-8") as f:
        f.write(content)
    logger.info(f"📄 草稿已保存: {draft_file}")
    return draft_file


def publish_article(title: str, body_markdown: str, tags: List[str],
                    published: bool = True, series: Optional[str] = None) -> Dict:
    """通过 dev.to API 发布文章"""
    api_key = get_devto_api_key()

    data = {
        "article": {
            "title": title,
            "body_markdown": body_markdown,
            "tags": tags[:4],  # dev.to 最多 4 个标签
            "published": published,
        }
    }
    if series:
        data["article"]["series"] = series

    headers = {
        "api-key": api_key,
        "Content-Type": "application/json",
    }

    logger.info(f"📤 发布文章到 dev.to: {title}")
    resp = requests.post(
        f"{DEVTO_API_BASE}/articles",
        headers=headers,
        json=data,
        timeout=30
    )

    if resp.status_code in (200, 201):
        result = resp.json()
        url = result.get("url", "")
        article_id = result.get("id", "")
        logger.info(f"✅ 文章发布成功: {url}")
        return {"success": True, "url": url, "id": article_id, "data": result}
    else:
        error_msg = resp.text[:500]
        logger.error(f"❌ 发布失败 ({resp.status_code}): {error_msg}")
        return {"success": False, "status_code": resp.status_code, "error": error_msg}


def generate_article(product_url: str, custom_instructions: str = "") -> Optional[Dict]:
    """调用 LLM 生成文章"""
    prompt_template = read_prompt()

    system_msg = "You are a technical writer publishing on dev.to. Generate articles in English."
    user_msg = f"""Product URL: {product_url}

{prompt_template}

{f"Additional instructions: {custom_instructions}" if custom_instructions else ""}

Generate the article as a JSON with these fields:
- "title": Article title (max 80 chars, hook-driven)
- "body_markdown": Full article in Markdown format (800-1500 words)
- "tags": Array of 3-4 tags (valid dev.to tags like: ai, python, webdev, api, tutorial, opensource, productivity, showdev, discuss, javascript, react, devops)
- "description": A short description (max 200 chars)
- "canonical_url": (optional) if this article was originally published elsewhere
"""

    logger.info(f"🤖 LLM 生成文章中... ({product_url})")
    result = call_llm_json(system_msg, user_msg, model="deepseek-v4-flash")

    if not result:
        logger.error("❌ LLM 返回为空")
        return None

    title = result.get("title", "").strip()
    body = result.get("body_markdown", "").strip()
    tags = result.get("tags", [])[:4]

    if not title or not body:
        logger.error("❌ LLM 生成内容不完整")
        return None

    return {"title": title, "body_markdown": body, "tags": tags, "description": result.get("description", "")}


def format_preview(title: str, body: str, tags: List[str]) -> str:
    """生成文章预览文本"""
    preview_body = body[:300] + "..." if len(body) > 300 else body
    return f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📌 Title: {title}
🏷️ Tags: {', '.join(tags)}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{preview_body}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""


def main():
    parser = argparse.ArgumentParser(description="dev.to 文章生成+发布")
    parser.add_argument("--product-url", required=True, help="产品链接")
    parser.add_argument("--dry-run", action="store_true", help="测试模式，只生成不发布")
    parser.add_argument("--auto-confirm", action="store_true", help="自动确认发布（非交互）")
    parser.add_argument("--custom-instructions", default="", help="额外的文章生成指令")
    parser.add_argument("--series", default="", help="文章所属系列名称")
    parser.add_argument("--publish-as-draft", action="store_true", help="发布为草稿（不公开）")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    # Step 1: LLM 生成文章
    article = generate_article(args.product_url, args.custom_instructions)
    if not article:
        sys.exit(1)

    title = article["title"]
    body = article["body_markdown"]
    tags = article["tags"]

    # Step 2: 保存草稿
    draft_file = save_draft(title, body, tags)
    print(format_preview(title, body, tags))

    # Step 3: 确认发布
    if args.dry_run:
        logger.info("🏁 测试模式，不发布。草稿已保存。")
        return

    if not args.auto_confirm:
        confirm = input("❓ 是否发布到 dev.to？(y/n): ").strip().lower()
        if confirm != "y":
            logger.info("⏭️ 已取消发布")
            return

    # Step 4: 发布
    result = publish_article(
        title=title,
        body_markdown=body,
        tags=tags,
        published=not args.publish_as_draft,
        series=args.series if args.series else None,
    )

    if result["success"]:
        # Step 5: 记录发布历史
        published = load_published()
        published.append({
            "id": result["id"],
            "url": result["url"],
            "title": title,
            "tags": tags,
            "published_at": datetime.now(timezone.utc).isoformat(),
            "product_url": args.product_url,
        })
        save_published(published)
        logger.info(f"✅ 完成! 文章地址: {result['url']}")
    else:
        logger.error(f"❌ 发布失败: {result.get('error', '未知错误')}")
        sys.exit(1)


if __name__ == "__main__":
    main()
