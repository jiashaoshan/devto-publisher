# BrowserWing 脚本: devto评论帖子

## 基本信息

- **名称**: devto评论帖子
- **ID**: `8fda52e1-f197-4ed5-8ee6-8dec3d555a74`
- **用途**: 在 dev.to 文章评论区发表评论
- **URL 模板**: `${链接}`

## 参数

| 参数 | 说明 | 示例 |
|------|------|------|
| `${内容}` | 要发表的评论内容 | "Great post! Thanks for sharing" |
| `${链接}` | 目标文章 URL | https://dev.to/username/article-slug |

## 执行步骤

| # | 操作 | 说明 |
|---|------|------|
| 1 | sleep 0.9s | 等待页面加载 |
| 2 | sleep 1.3s | 等待评论区加载 |
| 3 | input `#text-area` | 在评论区输入框填入评论内容 |
| 4 | click Submit 按钮 | 点击发表 |
| 5 | sleep 1s | 等待发表完成 |

## 导入命令

```bash
curl -X POST http://127.0.0.1:8080/api/v1/scripts/8fda52e1-f197-4ed5-8ee6-8dec3d555a74/play \
  -H "Content-Type: application/json" \
  -d '{"params": {"内容": "评论内容", "链接": "https://dev.to/..."}}'
```
