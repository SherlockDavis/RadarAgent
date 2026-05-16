# RadarAgent

一个 24 小时跑在云端的**个人情报 Web 平台**。用户在浏览器里配置自己关心的领域、信息源、推送方式，系统持续抓取多语言信息、由 LLM 过滤打分、构建可语义检索的知识库，并按订阅规则推送简报、回答用户随时的提问。

无论关注技术、金融、学术、行业新闻还是其他领域，资讯都分散在多个平台、多种语言中。RadarAgent 让用户在一个 Web 界面里管理多条情报订阅、收推送、做问答，把碎片化信息流变成可查询、可对话的私人知识库。

**RadarAgent 是产品；其底层的插件 / Provider / Notifier 抽象在架构上可以被当框架复用。** 产品是主，框架是副产品。

## 与"消息推送机器人"的区别

- 飞书 / Telegram bot + RSS 脚本 = **dumb pipe**：你发指令、它转消息
- RadarAgent = **smart agent**：它 24/7 主动观察、过滤、连接历史、生成洞察；你订阅 + 问答即可

## 核心架构

8 层数据流：

```
1. 数据源层（Plugin System）            抓取
2. 调度层（Parallel Scheduler）         并行 / 隔离 / 重试
3. 处理层（Filter + Translate + Score） LLMProvider 抽象，per-subscription 评分
4. RAG 知识库层（Vector Store）         全局文章 + per-user score / summary
5. 用户与订阅层（User + Subscription）  谁要什么样的信息以什么频率到什么渠道
6. 服务接口层（ServiceAPI）             generate_digest / query / search
7. Web 应用层（FastAPI + HTML/JS）      登录、订阅管理、Dashboard、问答、检索
8. 推送层（Notifier）                   Email（MVP）+ 未来 飞书 / Telegram / Webhook
```

## 核心抽象

**SourcePlugin**（已有）：数据源插件基类，`fetch() -> list[RawArticle]` + `get_schedule() -> str`。

**数据模型**：
- `RawArticle`（已有）：title / url / content / source / language / timestamp / metadata
- `ProcessedArticle`（已有）：raw + relevance_score + summary + tags + key_insight + is_duplicate
- `User`（新）：id / email / password_hash / created_at / output_language
- `Subscription`（新）：id / user_id / name / interest_profile / filter（keywords_boost/ignore, min_score, source_whitelist）/ schedule（cron）/ channels（list of {type, config}）/ format（digest | alert | summary）

文章在 RAG 全局存一份，**评分 + 摘要按 (article_id, subscription_id) 维度存**——同一篇 HN 文章对不同订阅可以打不同分。

**LLMProvider**（已有）：score_and_summarize / generate_digest / 不再含 embed（已迁移）。

**EmbeddingProvider**（已有）：local（bge-m3）/ openai。

**Notifier**（Phase 4 引入）：`send(content, channel_config) -> bool`。MVP 实现 EmailNotifier。

**ServiceAPI**（Phase 3 引入）：
- `generate_digest(subscription_id, date)` 按订阅生成简报
- `query(user_id, question)` 在用户的 RAG 范围内问答
- `search(user_id, filters)` 过滤检索

## 数据流细节

**调度层**：APScheduler 多 job —— 每个插件按自己 cron 抓取（全局，所有用户共享抓取结果）；每个订阅按 `Subscription.schedule` 跑简报 job（per-user / per-subscription）。

**处理层**：每条新文章 × 每个订阅 → LLM 评分一次（per-subscription profile 拼进 prompt）。低分丢弃，高分入该订阅的 per-user RAG 视图。

**Web 层**：FastAPI + 原生 HTML/JS，Jinja2 模板，session cookie 鉴权。MVP 页面：
- `/login` `/register` 认证
- `/` Dashboard：我的订阅列表 + 最近简报
- `/subscriptions/new` 创建订阅
- `/digest/{subscription_id}/{date}` 简报详情
- `/ask` 问答（POST /api/query）
- `/search` 检索

**推送层**：daemon 内 scheduler 跑 digest job → `ServiceAPI.generate_digest()` → 遍历订阅的 channels → `EmailNotifier.send()`。

## 配置体系

**系统级配置 `config/settings.yaml`**：LLM provider / embedding / storage / plugins / SMTP / 全局 schedule 默认值。**不再含 interests**——兴趣描述移到数据库的 `Subscription.interest_profile`，由 Web UI 编辑。

**用户级配置**：数据库 `users` + `subscriptions` 表。

**首次部署引导**：第一次启动时如果 `users` 表为空，命令行让你创建管理员账号（你自己）。之后通过 Web 管理。

## 插件体系

**核心通用插件**（`src/plugins/`，已有）：RSSPlugin + HTTPAPIPlugin。

**示例插件**（`src/plugins/examples/`，已有）：HackerNews / arXiv / SEC EDGAR。

新增插件类型 = 实现 SourcePlugin + 在注册表加一行（保持框架特性）。

## 项目结构

```
RadarAgent/
├── .github/                  PR / Issue 模板 + workflows/ci.yml
├── config/                   settings.yaml + 部署默认值
├── docs/                     plugins.md + providers.md + superpowers/specs/
├── src/radaragent/
│   ├── plugins/              base.py + rss.py + http_api.py + examples/
│   ├── scheduler/            scheduler.py
│   ├── processor/            llm_filter.py + dedup.py
│   ├── providers/            llm/ + embedding/ + notifier/
│   ├── storage/              rag.py + models.py + db.py（用户/订阅持久化）
│   ├── users/                models + auth + sessions
│   ├── subscriptions/        models + crud + scheduler_integration
│   ├── service/              api.py（ServiceAPI）+ digest.py + query.py
│   ├── web/                  app.py + routes/ + templates/ + static/
│   └── main.py               daemon 入口
├── tests/
├── pyproject.toml
├── Dockerfile + docker-compose.yaml
└── ... (Git/CI 配套不变)
```

## 技术栈

Python 3.11+ / asyncio + aiohttp / APScheduler / **FastAPI + uvicorn / Jinja2** / OpenAI 兼容（含 DeepSeek） / sentence-transformers (bge-m3) / Chroma / **SQLite（用户/订阅持久化，部署简单）** / **bcrypt（密码哈希）** / aiosmtplib（邮件）/ Docker / PyYAML + pydantic / pyproject.toml + uv 或 pip。

## 开发计划

**Phase 1 MVP**（已完成）：SourcePlugin + RSSPlugin + OpenAILLMProvider + 调度器 + 控制台输出。

**Phase 2 多源 + 存储 + Provider**（已完成）：HTTPAPIPlugin + 5 个示例插件 + Chroma RAG + 去重 + EmbeddingProvider 抽象。

**Phase 3 用户化重构 + 后端服务**：User / Subscription 数据模型 + SQLite 持久化 + 认证（注册/登录/session）+ ServiceAPI（digest + query）+ scheduler 改造为 per-subscription job + EmailNotifier。后端就绪，CLI 可触发。

**Phase 4 Web 应用 + 部署**：FastAPI 集成（登录 / Dashboard / 订阅管理 / 简报详情 / 问答 / 检索 6 个页面）+ Dockerfile + docker-compose + VPS 部署文档 + Caddy/Nginx 反代。**此时 v0.1.0 → main**。

**Phase 5 生产化**：Anthropic LLMProvider 备选 + 监控告警 + pre-commit 完整启用 + 性能优化（batch embedding / 缓存）+ 运行时插件管理。

**Phase 6 扩展通道**：飞书 / Telegram / Webhook Notifier + 实时告警类订阅（不是按日 cron，而是 fetch hit 立刻推）+ Web 视觉打磨 / 暗黑模式 / PWA。

**Phase 7 多用户开放**：注册开放（目前是单账号自填）+ 资源配额 + 按 user_id 切分 RAG（已经在架构里预埋）+ 多语言 UI。

## 关键设计原则

1. **产品优先**：每个 phase 完成都该让产品体感更完整，不只是抽象更优雅
2. **多用户架构、单用户首发**：schema 从第一天就有 user_id，但 MVP 只你一个账号
3. **插件优先**：新数据源都是 plugin 文件，不改核心
4. **故障隔离**：单源挂掉不影响整体；一个用户的订阅挂掉不影响其他用户
5. **成本控制**：抓取共享（一篇 HN 不抓 N 次），评分按订阅独立（per-subscription 模型可便宜可贵）
6. **多语言友好**：原文做 embedding，输出语言由用户设置决定
7. **渐进式复杂度**：每个 phase 独立可运行
8. **Provider 抽象**：LLM、Embedding、Notifier 可替换

## Git 工作流

**提交规范**：Conventional Commits。`<type>(<scope>): <subject>`。type 取 `feat` / `fix` / `docs` / `refactor` / `test` / `chore` / `perf` / `ci`。scope 取 `plugin` / `scheduler` / `processor` / `rag` / `output` / `config` / `provider` / `service`。

**分支策略**：

| 分支 | 用途 | 来源 → 目标 |
|---|---|---|
| `main` | 稳定发布 | — |
| `develop` | 集成 | `main` → `main`（release 时） |
| `feature/<topic>` | 新功能 | `develop` → `develop`（PR） |
| `fix/<issue-id>` | 常规 bug 修复 | `develop` → `develop`（PR） |
| `release/<version>` | 发布准备 | `develop` → `main` + `develop` |
| `hotfix/<issue-id>` | 线上紧急修复 | `main` → `main` + `develop` |

**PR 流程**：禁止直接 push 到 `main` / `develop`。PR 标题遵循 Conventional Commits。模板要求填变更摘要 / 动机 / 测试方式 / 关联 issue。至少 1 reviewer approve（单人开发可放宽，CI 必须绿）。

**配套文件**：`.gitignore` / `.gitattributes` / `.editorconfig` / `.pre-commit-config.yaml` / `CHANGELOG.md` / `LICENSE` / `.github/{PULL_REQUEST_TEMPLATE.md, ISSUE_TEMPLATE/, workflows/ci.yml}`。

**pre-commit**：`ruff check` + `ruff format` + `mypy src/` + `commitlint`。禁提 `.env` / `__pycache__` / `data/chroma`。

**CHANGELOG**：[Keep a Changelog](https://keepachangelog.com/) 格式，PR 作者合入前更新 `Unreleased`。

**版本号**：SemVer。MVP 阶段 `0.x.y`，首个公开版本 `1.0.0`。

**Commit 签名**：强制 SSH 签名。
```bash
git config --global gpg.format ssh
git config --global user.signingkey ~/.ssh/id_ed25519.pub
git config --global commit.gpgsign true
git config --global tag.gpgsign true
```
GitHub 仓库开启 "Require signed commits"。

**LICENSE**：MIT。源文件可选加 SPDX 头：`# SPDX-License-Identifier: MIT`。
