#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dev.to 评论区获客脚本
功能：搜索文章 → AI评分筛选 → LLM生成评论 → 自动评论

架构参考 juejin-publisher 的 juejin_acquisition.py，差异：
  - dev.to 使用 API Key 认证（非 Cookie）
  - 搜索: GET /api/articles?query=KEYWORD
  - 评论: POST /api/comments
  - 文章内容获取: GET /api/articles/:id
"""

import sys
import os
import json
import argparse
import requests
import time
import random
import logging
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any, Tuple
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# ─── 模块路径 ─────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent.absolute()
SKILL_DIR = SCRIPT_DIR.parent

# 导入 dev.to 专用 LLM 模块（使用 openclaw 配置的 baiduqianfancodingplan）
sys.path.insert(0, str(SCRIPT_DIR))
try:
    from devto_llm import call_llm_json, call_llm
except ImportError:
    call_llm = None
    call_llm_json = None

# ─── 路径配置 ─────────────────────────────────────────────
DATA_DIR = SKILL_DIR / "data"
COMMENTED_FILE = DATA_DIR / "commented-history.json"
COMMENT_TEMPLATE_FILE = SKILL_DIR / "templates" / "comment-strategic.md"

# dev.to API
DEVTO_API_BASE = "https://dev.to/api"

DATA_DIR.mkdir(parents=True, exist_ok=True)

# ─── 日志 ─────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(str(SKILL_DIR / "devto_acquisition.log"), encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ─── 配置 ─────────────────────────────────────────────────
DEFAULT_MAX_COMMENTS = 10
COMMENT_INTERVAL_MIN = 60   # 每条评论间隔最少60秒
COMMENT_INTERVAL_MAX = 180  # 最多180秒
DAILY_LIMIT = 20            # 每日评论上限
HOURLY_LIMIT = 5            # 每小时评论上限


def load_env() -> Dict[str, str]:
    """加载 .env 配置"""
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
    key = os.environ.get("DEVTO_API_KEY", "")
    if key:
        return key
    env = load_env()
    key = env.get("DEVTO_API_KEY", "")
    if key:
        return key
    try:
        with open(os.path.expanduser("~/.openclaw/openclaw.json")) as f:
            oc = json.load(f)
        env_config = oc.get("env", {})
        if isinstance(env_config, dict):
            for k, v in env_config.items():
                if "devto" in k.lower() and "api" in k.lower():
                    if isinstance(v, str) and v.strip():
                        return v.strip()
    except Exception:
        pass
    raise ValueError("DEVTO_API_KEY 未配置")


def get_headers() -> Dict[str, str]:
    return {
        "api-key": get_devto_api_key(),
        "Content-Type": "application/json",
        "Accept": "application/vnd.forem.api-v1+json",
    }


# ─── 历史记录管理 ─────────────────────────────────────────

def load_history(file: Path) -> list:
    """加载历史记录，返回列表，兼容旧格式"""
    if file.exists():
        try:
            data = json.load(open(file))
            # 兼容旧格式（纯 ID 列表）
            if data and isinstance(data[0], str):
                data = [{"article_id": id} for id in data]
            return data
        except (json.JSONDecodeError, IndexError):
            return []
    return []


def save_history(file: Path, history: list):
    with open(file, "w") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


# ─── 搜索文章 ─────────────────────────────────────────────

def search_articles(query: str, per_page: int = 50) -> List[Dict]:
    """通过 dev.to API 搜索文章"""
    params = {"query": query, "per_page": min(per_page, 100)}
    try:
        resp = requests.get(
            f"{DEVTO_API_BASE}/articles",
            params=params,
            headers=get_headers(),
            timeout=15
        )
        if resp.status_code == 200:
            articles = resp.json()
            logger.info(f"🔍 搜索 '{query}': 找到 {len(articles)} 篇文章")
            return articles
        else:
            logger.warning(f"搜索失败: {resp.status_code} {resp.text[:200]}")
            return []
    except Exception as e:
        logger.error(f"搜索异常: {e}")
        return []


def get_article_detail(article_id: int) -> Optional[Dict]:
    """获取文章详情"""
    try:
        resp = requests.get(
            f"{DEVTO_API_BASE}/articles/{article_id}",
            headers=get_headers(),
            timeout=15
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        logger.error(f"获取文章详情失败: {e}")
    return None


# ─── AI 评分筛选 ─────────────────────────────────────────

def score_article(article: Dict) -> float:
    """给文章评分的简化版（dev.to 数据比掘金丰富）"""
    score = 0

    # 热度 (40分)
    reactions = article.get("public_reactions_count", 0) or 0
    comments = article.get("comments_count", 0) or 0
    score += min(reactions * 0.5, 30)       # 最多30分
    score += min(comments * 2, 10)           # 最多10分

    # 时效 (20分) — 越新越好
    published = article.get("published_timestamp", "")
    if published:
        try:
            pub_date = datetime.fromisoformat(published.replace("Z", "+00:00"))
            days_ago = (datetime.now(timezone.utc) - pub_date).days
            score += max(0, 20 - days_ago)   # 每天减1分
        except Exception:
            score += 10

    # 质量 (10分) — 有封面图加分
    if article.get("cover_image"):
        score += 5
    if article.get("description") and len(article.get("description", "")) > 50:
        score += 5

    return score


def ai_score_articles(articles: List[Dict], product_keywords: str) -> List[Tuple[Dict, float]]:
    """评分筛选文章 — 使用规则评分（稳定快速，不限流）"""
    scored = [(a, score_article(a)) for a in articles]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


# ─── 评论生成 ─────────────────────────────────────────────

def generate_comment(article: Dict, product_keywords: str) -> Optional[str]:
    """LLM 生成评论"""
    if not call_llm:
        logger.warning("LLM 不可用，无法生成评论")
        return None

    title = article.get("title", "")
    description = article.get("description", "") or ""
    tags = article.get("tag_list", [])
    url = article.get("url", "")

    template = ""
    if COMMENT_TEMPLATE_FILE.exists():
        with open(COMMENT_TEMPLATE_FILE) as f:
            template = f.read()

    prompt = f"""Read this dev.to article and write a thoughtful comment.

Article Title: {title}
Tags: {', '.join(tags)}
Description: {description}

Context: We are doing developer community engagement related to: {product_keywords}

{template}

Return ONLY the comment text, 2-4 sentences, no JSON formatting.
Comment should sound like a real developer, NOT like marketing."""

    try:
        comment = call_llm("You are a developer writing a thoughtful comment on dev.to", prompt)
        if comment:
            comment = comment.strip().strip('"').strip("'")
            if len(comment) > 20:
                return comment
    except Exception as e:
        logger.error(f"评论生成失败: {e}")
    return None


# ─── 发布评论 ─────────────────────────────────────────────

def publish_comment(article_id: int, comment_body: str, article_url: str = "") -> bool:
    """通过 BrowserWing 脚本发布评论到 dev.to"""
    script_url = "http://127.0.0.1:8080/api/v1/scripts/8fda52e1-f197-4ed5-8ee6-8dec3d555a74/play"

    if not article_url:
        # 从 article_id 构造 URL（不准确，尽量传入真实 URL）
        article_url = f"https://dev.to/api/articles/{article_id}"

    payload = {
        "params": {
            "内容": comment_body,
            "链接": article_url
        }
    }

    try:
        resp = requests.post(script_url, json=payload, timeout=120)
        result = resp.json()
        success = result.get("result", {}).get("success")
        if success:
            logger.info(f"✅ 评论成功: {article_url}")
            return True
        else:
            error = result.get("result", {}).get("errors", "")
            logger.warning(f"❌ 评论失败: {error}")
            return False
    except Exception as e:
        logger.error(f"评论异常: {e}")
        return False


# ─── 生成搜索关键词 ───────────────────────────────────────

def generate_keywords(product_url: str) -> List[str]:
    """LLM 生成搜索关键词"""
    if not call_llm_json:
        return ["AI", "API", "developer tools", "python", "web development"]

    prompt = f"""Generate 8 search keywords (in English) for finding relevant articles on dev.to about a product at: {product_url}

Keywords should be topics that developers writing on dev.to would use (like: "AI API", "REST API", "developer tools", "web development", "Python library").
Return ONLY a JSON array of strings. No other text."""

    try:
        result = call_llm_json("You are a keyword generation assistant.", prompt)
        if isinstance(result, list) and len(result) > 0:
            keywords = [str(k).strip() for k in result if str(k).strip()]
            logger.info(f"🔑 生成关键词: {keywords}")
            return keywords[:8]
    except Exception as e:
        logger.warning(f"关键词生成失败: {e}")

    return ["AI", "API", "developer tools", "python", "tutorial", "webdev", "opensource", "productivity"]


# ─── 并发辅助函数 ─────────────────────────────────────────

def _fetch_and_generate(article_id: int, product_keywords: str) -> Tuple[Optional[int], Optional[str]]:
    """获取文章详情 + 生成评论（用于并发）"""
    try:
        detail = get_article_detail(article_id)
        if not detail:
            return (article_id, None)
        comment = generate_comment(detail, product_keywords)
        return (article_id, comment)
    except Exception as e:
        logger.warning(f"  _fetch_and_generate({article_id}) 异常: {e}")
        return (article_id, None)


# ─── 主流程 ───────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="dev.to 评论区获客")
    parser.add_argument("action", choices=["auto", "search", "comment", "history"], help="操作类型: auto=全自动, search=搜索, comment=评论指定文章, history=查看评论记录")
    parser.add_argument("--product-url", default="", help="产品链接（auto/search 模式）")
    parser.add_argument("--keyword", default="", help="搜索关键词（search 模式）")
    parser.add_argument("--max-comments", type=int, default=DEFAULT_MAX_COMMENTS, help="最大评论数")
    parser.add_argument("--dry-run", action="store_true", help="测试模式，不实际发表")
    parser.add_argument("--article-url", default="", help="评论指定文章（URL）")
    args = parser.parse_args()

    product_keywords = args.product_url or args.keyword or "developer tools"

    if args.action == "search":
        keyword = args.keyword or args.product_url or "AI"
        articles = search_articles(keyword)
        scored = ai_score_articles(articles, product_keywords)
        print(f"\n🔍 搜索 '{keyword}' 结果 (按评分排序):\n")
        for article, score in scored[:15]:
            reactions = article.get("public_reactions_count", 0)
            comments = article.get("comments_count", 0)
            title = article.get("title", "")[:60]
            url = article.get("url", "")
            print(f"  [{score:3.0f}分] 👍{reactions} 💬{comments} | {title}")
            print(f"         {url}")
        return

    if args.action == "history":
        """查看评论历史"""
        history = load_history(COMMENTED_FILE)
        if not history:
            print("📭 还没有评论记录")
            return
        print(f"\n📝 共 {len(history)} 条评论记录:\n")
        for i, item in enumerate(history, 1):
            title = item.get("title", "-")
            url = item.get("url", "-")
            comment = item.get("comment", "")[:100]
            ts = item.get("commented_at", "")[:19] if item.get("commented_at") else "-"
            print(f"  [{i}] {title}")
            print(f"      {url}")
            print(f"      评论: {comment}...")
            print(f"      时间: {ts}\n")
        return

    if args.action == "comment":
        if not args.article_url:
            logger.error("请提供 --article-url")
            return
        # 从 URL 提取文章 ID
        article_id = None
        if "/" in args.article_url:
            slug = args.article_url.rstrip("/").split("/")[-1]
            # dev.to URL format: dev.to/username/slug-1a2b
            # We need to get the article by URL or search for it
            articles = search_articles(slug)
            for a in articles:
                if a.get("url") == args.article_url:
                    article_id = a.get("id")
                    break
        if not article_id:
            logger.error("无法从 URL 获取文章 ID")
            return

        article_detail = get_article_detail(article_id)
        if not article_detail:
            logger.error("无法获取文章详情")
            return

        comment = generate_comment(article_detail, product_keywords)
        if not comment:
            logger.error("评论生成失败")
            return

        print(f"\n💬 生成的评论:\n{comment}\n")

        if not args.dry_run:
            confirm = input("❓ 发布此评论？(y/n): ").strip().lower()
            if confirm == "y":
                if publish_comment(article_id, comment, args.article_url):
                    history = load_history(COMMENTED_FILE)
                    history.append(str(article_id))
                    save_history(COMMENTED_FILE, history)
            else:
                logger.info("⏭️ 已取消")
        return

    # auto 模式：全自动获客
    logger.info("🚀 启动 dev.to 评论区获客 (auto 模式)")

    # Step 1: 生成关键词
    keywords = generate_keywords(args.product_url)

    # Step 2: 搜索文章
    all_articles = []
    seen_ids = set()
    for kw in keywords:
        articles = search_articles(kw, per_page=20)
        for a in articles:
            aid = a.get("id")
            if aid and aid not in seen_ids:
                seen_ids.add(aid)
                all_articles.append(a)
        time.sleep(1)

    logger.info(f"📚 去重后共 {len(all_articles)} 篇文章")

    if not all_articles:
        logger.warning("没有找到文章")
        return

    # Step 3: AI 评分筛选
    scored = ai_score_articles(all_articles, product_keywords)
    top_articles = [a for a, s in scored[:args.max_comments * 2]]  # 多筛一些备用

    # Step 4: 加载历史，去重
    commented_history = load_history(COMMENTED_FILE)
    fresh_articles = [a for a in top_articles if str(a.get("id")) not in commented_history]
    fresh_articles = fresh_articles[:args.max_comments]

    logger.info(f"🎯 待评论文章: {len(fresh_articles)} 篇 (已去重)")

    if not fresh_articles:
        logger.info("没有需要评论的新文章")
        return

    # Step 5: 并发获取文章详情 + 并发生成评论
    logger.info(f"⏳ 并发获取 {len(fresh_articles)} 篇文章详情并生成评论...")

    comment_results: List[Tuple[Optional[int], Optional[str]]] = [None] * len(fresh_articles)

    with ThreadPoolExecutor(max_workers=5) as executor:
        # 提交所有任务
        future_map = {}
        for idx, article in enumerate(fresh_articles):
            article_id = article.get("id")
            future = executor.submit(_fetch_and_generate, article_id, product_keywords)
            future_map[future] = idx

        # 收集结果
        for future in as_completed(future_map):
            idx = future_map[future]
            try:
                article_id, comment = future.result()
                comment_results[idx] = (article_id, comment)
                title = fresh_articles[idx].get("title", "")[:40]
                if comment:
                    logger.info(f"  ✅ [{idx+1}] 评论已生成: {title}")
                else:
                    logger.warning(f"  ❌ [{idx+1}] 生成失败: {title}")
            except Exception as e:
                logger.warning(f"  ❌ [{future_map[future]+1}] 异常: {e}")
                comment_results[future_map[future]] = (None, None)

    # Step 6: 串行发表评论（保持间隔，防封）
    logger.info(f"\n📤 开始串行发表评论 ({len([r for r in comment_results if r and r[1]])} 条)...")
    commented_count = 0

    for idx, result in enumerate(comment_results):
        if not result or not result[1]:
            continue

        article_id, comment = result
        if not article_id or not comment:
            continue

        title = fresh_articles[idx].get("title", "")[:40]
        print(f"  💬 [{idx+1}] 评论: {comment[:80]}...")

        if args.dry_run:
            logger.info(f"  🏁 [dry-run] 跳过发表: {title}")
        else:
            if publish_comment(article_id, comment, fresh_articles[idx].get("url", "")):
                commented_count += 1
                history = load_history(COMMENTED_FILE)
                history.append({
                    "article_id": str(article_id),
                    "title": fresh_articles[idx].get("title", ""),
                    "url": fresh_articles[idx].get("url", ""),
                    "comment": comment[:200],
                    "commented_at": datetime.now(timezone.utc).isoformat()
                })
                save_history(COMMENTED_FILE, history)
            else:
                logger.warning(f"  ❌ 发表失败: {title}")
                continue

        # 间隔等待（dry-run 跳过）
        if not args.dry_run:
            delay = random.randint(COMMENT_INTERVAL_MIN, COMMENT_INTERVAL_MAX)
            logger.info(f"  ⏳ 等待 {delay}s 后继续...")
            time.sleep(delay)

    logger.info(f"\n✅ 完成！成功评论 {commented_count} 篇")


if __name__ == "__main__":
    main()
