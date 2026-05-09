# RadarAgent CLAUDE.md 重构设计

**日期**: 2026-05-09
**状态**: 设计已与用户对齐，待用户审阅
**作者**: 通过 brainstorming skill 协作产出

---

## 背景

项目原名为 `tech-radar-agent`，定位是"个人技术情报系统"。CLAUDE.md 中所有抽象层、插件、配置、推送都强绑定技术领域（HackerNews / GitHub Trending / tech_stack / OpenAI / Telegram）。

用户希望：
1. 项目改名为 **RadarAgent**
2. 转型为**完全 domain-agnostic** 的情报系统框架（科技、金融、学术、新闻等领域均可适配）
3. 新增 **Git 工作流**章节（标准开源项目流程）
4. 优化现有 CLAUDE.md 表述与组织

本次产出范围限定为：**重写 CLAUDE.md 一个文件**。代码骨架、git init、配套文件等留作下次任务。

---

## 决策汇总（brainstorming 对齐结果）

| 维度 | 决策 |
|---|---|
| 通用化程度 | 完全 domain-agnostic 框架 |
| Git 流程粒度 | 标准开源项目流程（Conventional Commits + 分支策略 + PR 模板 + .gitignore + pre-commit + CHANGELOG） |
| 兴趣配置形式 | 纯自然语言 profile + keywords_boost/ignore |
| 预置插件策略 | 保留主流插件 + 多领域示例（科技 / 学术 / 金融 / 社区） |
| Provider 抽象 | LLM 和推送都抽象成 Provider 接口 |
| 前端 | 架构预留 HTTP API 层（服务接口层），Web UI 列入 Phase 5，本次不设计 |
| LICENSE | MIT |
| Commit 签名 | SSH（强制） |
| 重写策略 | 方案 B：重组 + 中性化 |

---

## 一、新 CLAUDE.md 章节骨架

```
# RadarAgent

## 项目定位            领域无关情报系统框架
## 核心架构概览         5 层数据流 + 服务接口层
## 核心抽象层           Plugin / 数据模型 / Provider 三组契约
## 插件体系             核心通用插件 + 多领域示例插件
## 配置体系             settings.yaml + interests.yaml（自然语言 profile）
## Git 工作流           新增章节
## 项目结构             目录树
## 开发计划             Phase 1-5
## 关键设计原则         扩展原版
```

---

## 二、项目定位（重写）

> RadarAgent 是一个领域无关的 24 小时情报系统框架。给定一组数据源、一份用户兴趣描述和一个推送渠道，它持续抓取多语言信息、由 LLM 过滤打分、构建可语义检索的知识库，并按计划生成简报推送给用户。
>
> 解决"信息过载"问题：无论你关注的是技术、金融、学术、行业新闻还是其他领域，相关资讯都分散在多个平台、多种语言中，手动跟踪低效且容易遗漏。RadarAgent 通过插件化数据源、可配置的兴趣 profile、可替换的 LLM 与推送 Provider，让用户用一份配置就能搭起自己的领域 radar。

**关键改动**：
- `tech-radar-agent` → `RadarAgent`
- "个人技术情报" → "领域无关的情报系统框架"
- 删除具体平台枚举，改用"插件化数据源"
- 强调"框架"属性

---

## 三、核心架构（5 层 + 服务接口层）

```
┌─────────────────────────────────────────┐
│ 1. 数据源层（Plugin System）             │ 抓取
├─────────────────────────────────────────┤
│ 2. 调度层（Parallel Scheduler）          │ 并行 / 隔离 / 重试
├─────────────────────────────────────────┤
│ 3. 处理层（Filter + Translate + Score）  │ LLMProvider 抽象
├─────────────────────────────────────────┤
│ 4. RAG 知识库层（Vector Store）          │ 长期记忆
├─────────────────────────────────────────┤
│ 5. 服务接口层（Internal API）            │ 简报 / 检索 / 订阅
└─────────────────────────────────────────┘
              ▲          ▲          ▲
              │          │          │
        Telegram Bot   CLI    Web UI（Phase 5）
              │          │          │
        Notifier Provider 抽象（推送渠道可替换）
```

**关键变化**：原"输出层"重新定位为**服务接口层**。Telegram Bot / CLI / 未来 Web UI 都是 ServiceAPI 的消费者，不直接耦合 RAG 或处理层。

---

## 四、核心抽象（契约）

### 4.1 SourcePlugin

```python
class SourcePlugin(ABC):
    """所有数据源插件的基类"""

    @abstractmethod
    async def fetch(self) -> list[RawArticle]:
        """抓取数据，返回统一格式的信息条目列表"""
        pass

    @abstractmethod
    def get_schedule(self) -> str:
        """返回 cron 表达式，定义抓取频率"""
        pass
```

### 4.2 数据模型

```python
@dataclass
class RawArticle:
    title: str
    url: str
    content: str
    source: str           # 数据源标识符
    language: str         # 原文语言代码
    timestamp: datetime
    metadata: dict        # 源特有的元数据

@dataclass
class ProcessedArticle:
    raw: RawArticle
    relevance_score: float    # 0-10
    summary: str              # 目标语言摘要（由 settings 配置）
    tags: list[str]
    key_insight: str          # 一句话核心要点
    is_duplicate: bool
```

**与原版差异**：`summary_zh` → `summary`；输出语言由 `settings.output_language` 决定，不写死。

### 4.3 LLMProvider（新抽象）

```python
class LLMProvider(ABC):
    @abstractmethod
    async def score_and_summarize(
        self, article: RawArticle, profile: str, output_language: str
    ) -> ProcessedArticle: ...

    @abstractmethod
    async def generate_digest(
        self, articles: list[ProcessedArticle], context: list[ProcessedArticle]
    ) -> str: ...

    @abstractmethod
    async def embed(self, text: str) -> list[float]: ...
```

默认实现：`OpenAILLMProvider`。预留：`AnthropicLLMProvider`、本地模型、兼容 API。

### 4.4 Notifier（新抽象）

```python
class Notifier(ABC):
    @abstractmethod
    async def send(self, content: str, channel_config: dict) -> bool: ...
```

默认实现：`TelegramNotifier`。Phase 3 内置：`EmailNotifier`、`WebhookNotifier`。`SlackNotifier` / `DiscordNotifier` 等通过 `WebhookNotifier` 通用支持，无需单独实现。

### 4.5 ServiceAPI（新抽象）

内部 API，Telegram Bot / CLI / 未来 Web UI 共享：

```python
class ServiceAPI:
    async def generate_digest(self, date: date) -> str: ...
    async def query(self, question: str) -> str: ...           # RAG 问答
    async def search(self, filters: SearchFilters) -> list[ProcessedArticle]: ...
```

---

## 五、插件体系

### 5.1 核心通用插件（`src/plugins/`）

- `RSSPlugin` —— 通用 RSS / Atom 读取器
- `HTTPAPIPlugin` —— 通用 REST API 抓取器（配 endpoint / 鉴权 / JSON 路径）

### 5.2 多领域示例插件（`src/plugins/examples/`）

| 领域 | 插件 | 数据源 |
|---|---|---|
| 科技 | `HackerNewsPlugin` | HN API |
| 学术 | `ArxivPlugin` | arXiv API（按 category） |
| 金融 | `SECEdgarPlugin` | SEC EDGAR |
| 社区 | `RedditPlugin` | Reddit API |
| 综合 | `GitHubTrendingPlugin` | GitHub Trending |

新增数据源 = 实现 `SourcePlugin` + 在 settings.yaml 中注册。`type` 字符串通过显式注册表绑定到实现类。

---

## 六、配置体系

### 6.1 settings.yaml

```yaml
llm:
  provider: openai                    # openai | anthropic | local | custom
  filter_model: gpt-4o-mini
  digest_model: gpt-4o
  api_key: ${OPENAI_API_KEY}

embedding:
  provider: openai
  model: text-embedding-3-small

storage:
  type: chroma                        # 二选一：chroma | qdrant
  chroma:
    persist_directory: ./data/chroma
  # qdrant:                           # 仅当 type: qdrant 时启用
  #   url: http://localhost:6333

plugins:
  - id: my-tech-feed
    type: rss
    config:
      urls:
        - https://lobste.rs/rss
      schedule: "*/30 * * * *"

  - id: arxiv-llm
    type: arxiv
    config:
      categories: [cs.LG, cs.CL]
      schedule: "0 */6 * * *"

output:
  digest_schedule: "0 8 * * *"
  output_language: zh
  notifiers:
    - type: telegram
      config:
        bot_token: ${TELEGRAM_BOT_TOKEN}
        chat_id: ${TELEGRAM_CHAT_ID}
    - type: email
      config:
        smtp_host: ...
```

### 6.2 interests.yaml（结构改造）

```yaml
profile: |
  我是一名关注东南亚商业机会的早期投资人。
  重点关注：印尼/越南/菲律宾市场的金融科技、电商、物流领域早期公司融资动态、
  关键政策变化、头部公司动向。不关心二级市场和加密货币。

keywords_boost:
  - Series A
  - 印尼
  - GoTo

keywords_ignore:
  - crypto
  - NFT
  - 二级市场

output_language: zh
min_relevance_score: 6
```

LLM 在打分时把 `profile` 段直接拼进 prompt。删除原版 `tech_stack` / `domains` 字段。`output_language` 与阈值移到此文件（语义上属于"用户兴趣"）。

---

## 七、Git 工作流（全新章节）

### 7.1 提交规范（Conventional Commits）

```
<type>(<scope>): <subject>

<body>

<footer>
```

**type**: `feat` / `fix` / `docs` / `refactor` / `test` / `chore` / `perf` / `ci`

**scope** 建议: `plugin` / `scheduler` / `processor` / `rag` / `output` / `config` / `provider` / `service`

例: `feat(plugin): add ArxivPlugin with category filter`

### 7.2 分支策略

| 分支 | 用途 | 来源 | 合并目标 |
|---|---|---|---|
| `main` | 稳定发布 | — | — |
| `develop` | 集成 | `main` | `main`（release 时）|
| `feature/<topic>` | 新功能 | `develop` | `develop`（PR）|
| `fix/<issue-id>` | 常规 bug 修复 | `develop` | `develop`（PR）|
| `release/<version>` | 发布准备 | `develop` | `main` + `develop` |
| `hotfix/<issue-id>` | 线上紧急 | `main` | `main` + `develop` |

### 7.3 PR 流程

- 所有变更通过 PR 合入，**禁止直接 push 到 `main` / `develop`**
- PR 标题遵循 Conventional Commits
- `.github/PULL_REQUEST_TEMPLATE.md` 要求填：变更摘要 / 动机 / 测试方式 / 关联 issue
- 至少 1 reviewer approve（单人开发阶段可放宽，但 CI 必须绿）

### 7.4 必备配套文件

```
.gitignore                  # Python + venv + .env + chroma data + logs + IDE
.gitattributes              # 行尾统一 LF
.editorconfig
.pre-commit-config.yaml
.github/
  PULL_REQUEST_TEMPLATE.md
  ISSUE_TEMPLATE/
    bug_report.md
    feature_request.md
  workflows/
    ci.yml
    release.yml
CHANGELOG.md
LICENSE                     # MIT
```

### 7.5 pre-commit 钩子

- `ruff check` + `ruff format`
- `mypy src/`
- `commitlint`
- 禁止提交 `.env` / `*.pyc` / `__pycache__` / `data/chroma`

### 7.6 CHANGELOG

遵循 [Keep a Changelog](https://keepachangelog.com/) 格式。每个版本含 `Added` / `Changed` / `Deprecated` / `Removed` / `Fixed` / `Security`。PR 作者在合并前更新 `Unreleased` 段。

### 7.7 版本号

SemVer: `MAJOR.MINOR.PATCH`。Phase 1 MVP 期间为 `0.x.y`，第一个公开版本 `1.0.0`。

### 7.8 Commit 签名

强制 SSH 签名:

```bash
git config --global gpg.format ssh
git config --global user.signingkey ~/.ssh/id_ed25519.pub
git config --global commit.gpgsign true
git config --global tag.gpgsign true
```

GitHub 仓库设置中开启 "Require signed commits"。

### 7.9 LICENSE

MIT License。仓库根 `LICENSE` 文件，每个源文件可选加简短 SPDX 头：`# SPDX-License-Identifier: MIT`。

---

## 八、项目结构

```
RadarAgent/
├── .github/
│   ├── PULL_REQUEST_TEMPLATE.md
│   ├── ISSUE_TEMPLATE/
│   └── workflows/
│       └── ci.yml
├── config/
│   ├── settings.yaml
│   └── interests.yaml
├── docs/
│   ├── plugins.md             # 如何写新插件
│   ├── providers.md           # 如何实现 LLMProvider/Notifier
│   └── superpowers/specs/     # brainstorming 产出
├── src/
│   ├── plugins/
│   │   ├── base.py            # SourcePlugin + RawArticle
│   │   ├── rss.py
│   │   ├── http_api.py
│   │   └── examples/
│   │       ├── hackernews.py
│   │       ├── github_trending.py
│   │       ├── arxiv.py
│   │       ├── sec_edgar.py
│   │       └── reddit.py
│   ├── scheduler/
│   │   └── scheduler.py
│   ├── processor/
│   │   ├── llm_filter.py
│   │   └── dedup.py
│   ├── providers/
│   │   ├── llm/
│   │   │   ├── base.py
│   │   │   ├── openai.py
│   │   │   └── anthropic.py
│   │   └── notifier/
│   │       ├── base.py
│   │       ├── telegram.py
│   │       ├── email.py
│   │       └── webhook.py
│   ├── storage/
│   │   ├── rag.py
│   │   └── models.py
│   ├── service/
│   │   └── api.py             # ServiceAPI
│   ├── output/
│   │   ├── digest.py
│   │   ├── telegram_bot.py
│   │   └── cli.py
│   └── main.py
├── tests/
│   ├── test_plugins/
│   ├── test_processor/
│   ├── test_providers/
│   └── test_storage/
├── .gitignore
├── .gitattributes
├── .editorconfig
├── .pre-commit-config.yaml
├── CHANGELOG.md
├── LICENSE
├── pyproject.toml             # 替代 requirements.txt
├── docker-compose.yaml
├── Dockerfile
└── README.md
```

---

## 九、开发计划

- **Phase 1: MVP** —— 调度器 + RSSPlugin + LLMProvider（OpenAI 实现）+ 控制台输出
- **Phase 2: 多源 + 存储 + Provider 完整化** —— HTTPAPIPlugin + 多领域示例插件 + Chroma RAG + 去重 + Anthropic LLMProvider
- **Phase 3: 服务接口 + 多渠道推送** —— ServiceAPI + 日报生成 + Telegram Bot + Email/Webhook Notifier + CLI 查询
- **Phase 4: 生产化** —— Docker Compose + 监控告警 + pre-commit/CI 接入 + 性能优化
- **Phase 5: Web 前端**（架构预留，本次不设计）—— 基于 ServiceAPI 的 Web Dashboard

---

## 十、关键设计原则

1. **插件优先**：任何新数据源都是一个 plugin 文件，不改动核心代码
2. **故障隔离**：单个源挂掉不影响整体运行
3. **成本控制**：过滤用便宜模型，生成用好模型；低分内容不进 RAG
4. **多语言友好**：原文做 embedding（语义更准），输出语言由 settings 决定
5. **渐进式复杂度**：从单源 + 控制台开始，每个 phase 独立可运行
6. **领域无关**（新增）：核心代码不假设任何特定领域，所有领域特性进 plugin 或 profile
7. **Provider 抽象**（新增）：LLM 与推送渠道可替换，避免厂商锁定

---

## 十一、技术栈

- **语言**: Python 3.11+
- **异步框架**: asyncio + aiohttp
- **调度**: APScheduler
- **LLM**: OpenAI（默认）/ Anthropic / 其他兼容 API（通过 LLMProvider 抽象）
- **Embedding**: text-embedding-3-small / bge-m3 / 其他
- **向量数据库**: Chroma（开发）→ Qdrant（生产）
- **推送**: python-telegram-bot（默认）+ Email / Webhook（通过 Notifier 抽象）
- **部署**: Docker Compose
- **配置管理**: PyYAML + pydantic
- **依赖管理**: pyproject.toml + uv 或 pip

---

## 范围声明

本次任务**仅产出新版 CLAUDE.md**。以下事项留作下次任务，不在本次范围：

- `git init` 与远程仓库创建
- 实际写入 `.gitignore` / `LICENSE` / `pyproject.toml` / `.pre-commit-config.yaml` 等配套文件
- 任何源代码骨架（SourcePlugin 基类、RSSPlugin 等）
- README.md 撰写
