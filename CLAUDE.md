# RadarAgent

一个领域无关的 24 小时情报系统框架。给定一组数据源、一份用户兴趣描述和一个推送渠道，它持续抓取多语言信息、由 LLM 过滤打分、构建可语义检索的知识库，并按计划生成简报推送给用户。

无论关注技术、金融、学术、行业新闻还是其他领域，资讯都分散在多个平台、多种语言中。RadarAgent 通过插件化数据源、可配置的兴趣 profile、可替换的 LLM 与推送 Provider，让用户用一份配置就能搭起自己的领域 radar。

本项目是**框架**，不是面向特定领域的成品。所有领域特性以插件、配置或 profile 形式接入；核心代码不假设任何特定领域。

详细设计见 `docs/superpowers/specs/2026-05-09-radaragent-redesign-design.md`。

## 核心架构

5 层数据流 + 1 层服务接口：

```
1. 数据源层（Plugin System）             抓取
2. 调度层（Parallel Scheduler）          并行 / 隔离 / 重试
3. 处理层（Filter + Translate + Score）  LLMProvider 抽象
4. RAG 知识库层（Vector Store）          长期记忆
5. 服务接口层（Internal API）            简报 / 检索 / 订阅
        ▲          ▲          ▲
   Telegram Bot   CLI    Web UI（Phase 5）
        ↑ 通过 Notifier Provider 抽象推送
```

Telegram Bot / CLI / 未来 Web UI 都是 ServiceAPI 的消费者，不直接耦合 RAG 或处理层。

## 核心抽象

可扩展性建立在三组契约上：

**SourcePlugin**：数据源插件基类。
- `fetch() -> list[RawArticle]` 抓取数据
- `get_schedule() -> str` 返回 cron 表达式

新增数据源 = 实现 `SourcePlugin` + 在 settings.yaml 注册，不改动调度器或下游。

**数据模型**：
- `RawArticle`：title / url / content / source / language / timestamp / metadata
- `ProcessedArticle`：raw + relevance_score (0-10) + summary + tags + key_insight + is_duplicate

`summary` 的语言由 `output_language` 配置决定，不写死。

**LLMProvider**：LLM 调用统一接口，避免厂商锁定。
- `score_and_summarize(article, profile, output_language) -> ProcessedArticle` 一次完成评分 + 翻译 + 摘要 + 标签
- `generate_digest(articles, context) -> str` 生成简报
- `embed(text) -> list[float]` 向量化

默认实现 `OpenAILLMProvider`。预留 Anthropic、本地模型、其他兼容 API。

**Notifier**：推送渠道统一接口。`send(content, channel_config) -> bool`。默认 Telegram，Phase 3 内置 Email + Webhook（Slack / Discord 通过 Webhook 通用支持）。

**ServiceAPI**：服务接口层暴露的内部 API，所有消费者共享。
- `generate_digest(date)` 简报生成
- `query(question)` RAG 问答
- `search(filters)` 过滤检索

新增消费者（如 Web UI）只调 ServiceAPI，不触碰 RAG / 处理层 / 调度层。

## 数据流细节

**调度层**：APScheduler 或 asyncio。每个 plugin 独立调度互不阻塞，单源失败不影响其他源（错误隔离 + 自动重试），支持运行时动态增减。所有抓取结果写统一 raw queue。

**处理层**：LLM prompt 一次完成四件事——相关性评分（基于 `interests.yaml` 的自然语言 profile + keywords_boost/ignore）、目标语言摘要、标签提取、去重判断。score >= `min_relevance_score` 的内容进 RAG 和简报。

**RAG 层**：原文与摘要分别 embedding（原文向量语义更准，摘要向量支持目标语言查询）。metadata 存 source / tags / score / timestamp / url / language。开发用 Chroma，生产可换 Qdrant / Milvus。

**输出**：被动推送（按 `digest_schedule` cron 通过所有配置的 Notifier 发送简报）+ 主动查询（Telegram Bot / CLI 通过 ServiceAPI 问答）。

## 插件体系

**核心通用插件**（`src/plugins/`）：
- `RSSPlugin` 通用 RSS / Atom 读取器
- `HTTPAPIPlugin` 通用 REST API 抓取器（配 endpoint / 鉴权 / JSON 路径）

**多领域示例插件**（`src/plugins/examples/`）：

| 领域 | 插件 | 数据源 |
|---|---|---|
| 科技 | `HackerNewsPlugin` | HN API |
| 综合 | `GitHubTrendingPlugin` | GitHub Trending |
| 学术 | `ArxivPlugin` | arXiv API |
| 金融 | `SECEdgarPlugin` | SEC EDGAR |
| 社区 | `RedditPlugin` | Reddit API |

`plugins[*].type` 字符串通过显式注册表绑定到实现类。新增插件类型 = 实现 + 注册一行。

## 配置体系

**`config/settings.yaml`**：LLM provider / embedding / storage / plugins 列表 / output（含 digest_schedule + notifiers 数组）。完整字段见 spec 文档。

**`config/interests.yaml`**：

```yaml
profile: |
  我是一名关注东南亚商业机会的早期投资人。
  重点关注：印尼/越南/菲律宾市场的金融科技、电商、物流领域早期公司融资动态。
  不关心二级市场和加密货币。

keywords_boost: [Series A, 印尼, GoTo]
keywords_ignore: [crypto, NFT]

output_language: zh
min_relevance_score: 6
max_articles_per_digest: 15
```

LLM 在打分时直接把 `profile` 段拼进 prompt。框架领域无关，不预设 `tech_stack` / `domains` 等结构化领域字段。

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

## 项目结构

```
RadarAgent/
├── .github/                  PR / Issue 模板 + workflows/ci.yml
├── config/                   settings.yaml + interests.yaml
├── docs/                     plugins.md + providers.md + superpowers/specs/
├── src/
│   ├── plugins/              base.py + rss.py + http_api.py + examples/
│   ├── scheduler/            scheduler.py
│   ├── processor/            llm_filter.py + dedup.py
│   ├── providers/            llm/{base,openai,anthropic}.py + notifier/{base,telegram,email,webhook}.py
│   ├── storage/              rag.py + models.py
│   ├── service/              api.py（ServiceAPI）
│   ├── output/               digest.py + telegram_bot.py + cli.py
│   └── main.py
├── tests/                    test_plugins/ + test_processor/ + test_providers/ + test_storage/
├── pyproject.toml            依赖 + 工具配置
├── docker-compose.yaml + Dockerfile
└── .gitignore / .gitattributes / .editorconfig / .pre-commit-config.yaml / CHANGELOG.md / LICENSE / README.md
```

## 技术栈

Python 3.11+ / asyncio + aiohttp / APScheduler / OpenAI（默认）+ Anthropic / text-embedding-3-small 或 bge-m3 / Chroma → Qdrant / python-telegram-bot + Email + Webhook / Docker Compose / PyYAML + pydantic / pyproject.toml + uv 或 pip。

## 开发计划

**Phase 1 MVP**：`SourcePlugin` 基类 + `RSSPlugin` + `OpenAILLMProvider` + 基础调度器 + 控制台输出。

**Phase 2 多源 + 存储 + Provider**：`HTTPAPIPlugin` + 五个领域示例插件 + 并行调度 + Chroma RAG + 去重 + `AnthropicLLMProvider`。

**Phase 3 服务接口 + 多渠道**：`ServiceAPI` + 简报生成 + `TelegramNotifier` + `EmailNotifier` + `WebhookNotifier` + CLI。

**Phase 4 生产化**：Docker Compose + 监控告警 + pre-commit / GitHub Actions CI + 性能优化（batch embedding / 缓存）+ 运行时插件管理。

**Phase 5 Web 前端**（架构已预留，本次不设计）：基于 ServiceAPI 的 Web Dashboard。

## 关键设计原则

1. **插件优先**：新数据源都是 plugin 文件，不改核心
2. **故障隔离**：单源挂掉不影响整体
3. **成本控制**：过滤用便宜模型，生成用好模型；低分内容不进 RAG
4. **多语言友好**：原文做 embedding，输出语言由 settings 决定
5. **渐进式复杂度**：每个 phase 独立可运行
6. **领域无关**：核心不假设任何领域，领域特性进 plugin 或 profile
7. **Provider 抽象**：LLM 与推送可替换，避免厂商锁定
