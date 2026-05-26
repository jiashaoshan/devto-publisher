# dev.to API 注意事项

> 最后更新: 2026-05-26

## 评论发布

- **dev.to 没有公开的创建评论 API** — `POST /api/comments` 返回 404
- 必须通过 BrowserWing 浏览器自动化发布评论
- 对应的 BW 脚本: `bw-scripts/devto-comment.json`

## API Key 要求

- **搜索文章**: 不需要 API Key (公开 API)
- **获取文章详情**: 不需要 API Key
- **创建评论 (BW)**: 不需要 API Key
- **发布文章**: 需要 API Key (dev.to 后台生成)

## API Key 读取优先级

`get_devto_api_key()` 按以下顺序查找：

1. 环境变量 `DEVTO_API_KEY`
2. `.env` 文件 (项目目录下)
3. `~/.hermes/.env` 文件 (Hermes 全局配置)
4. openclaw.json 的 `env.DEVTO_API_KEY`

## BrowserWing 配置

- 默认 URL: `http://127.0.0.1:8080`
- 可通过环境变量 `BROWSERWING_EXECUTOR_URL` 覆盖