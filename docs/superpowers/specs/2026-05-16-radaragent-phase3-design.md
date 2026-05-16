# RadarAgent Phase 3 设计：用户化重构 + 后端服务

**日期**: 2026-05-16
**状态**: 设计已与用户对齐，待用户审阅
**作者**: 通过 brainstorming skill 协作产出
**前置**: Phase 2b 已完成（Chroma RAG + 双向量去重 + EmbeddingProvider 抽象）；CLAUDE.md 已重写为多用户个人情报 Web 平台

---

## 背景

Phase 2 结束时系统是一个单租户管道：`config/interests.yaml` 一份兴趣描述 → 全局抓取 → LLM 打分 → Chroma → 控制台打印。CLAUDE.md 已在本轮 brainstorming 中重定位为 **24×7 多用户个人情报 Web 平台**（产品优先，框架是副产品）。

Phase 3 是"用户化重构 + 后端服务"：把单租户管道改造成 **多用户、多订阅** 的后端，所有能力先通过 CLI 可触发、可验证，Web 层留给 Phase 4。这一步不交付任何 HTML 页面。

**项目核心约束**：24×7 daemon 长驻是项目定义本身（见 memory `24/7 长驻是项目核心定义`）。任何带"何时触发"维度的功能都先设计 daemon 常驻路径，CLI 一次性触发是补充而非替代。

---

## 决策汇总（brainstorming 对齐结果）

| 维度 | 决策 |
|---|---|
| 用户模型 | 多用户架构、单用户首发：schema 第一天就带 `user_id`，MVP 只一个账号 |
| 持久化 | SQLite（用户/订阅/简报历史），与 Chroma 分离 |
| 密码 | bcrypt 哈希，明文永不落库 |
| 认证产物 | Phase 3 交付认证**后端**（注册/登录/校验/session token 生成）；session cookie 的 HTTP 绑定在 Phase 4 |
| 评分粒度 | per-(article_id, subscription_id)：同一篇文章对不同订阅可不同分 |
| 抓取粒度 | 全局共享：一篇 HN 只抓一次，所有订阅复用 |
| 简报内容 | 今日新增（该订阅高分新文章）+ RAG 历史上下文 |
| 触发模型 | daemon 内 APScheduler 跑 per-subscription digest job（首选）+ CLI 一次性触发（补充） |
| ServiceAPI 范围 | Phase 3 = `generate_digest` + `query`；`search` 接口预留签名，实现可滞后 |
| 推送渠道 | Phase 3 只做 EmailNotifier（aiosmtplib + SMTP）；飞书/Telegram/Webhook 推到 Phase 6 |
| interests.yaml | 删除，迁移到 DB 的 `Subscription.interest_profile`；首启引导建管理员账号 + 一条默认订阅 |

---

## 一、数据模型

### SQLite schema（`src/radaragent/storage/db.py`）

```
users
  id               INTEGER PK
  email            TEXT UNIQUE NOT NULL
  password_hash    TEXT NOT NULL          -- bcrypt
  output_language  TEXT NOT NULL DEFAULT 'zh'
  is_admin         INTEGER NOT NULL DEFAULT 0
  created_at       TEXT NOT NULL          -- ISO8601 UTC

subscriptions
  id               INTEGER PK
  user_id          INTEGER NOT NULL FK->users.id
  name             TEXT NOT NULL
  interest_profile TEXT NOT NULL          -- 自然语言，拼进打分 prompt
  filter_json      TEXT NOT NULL          -- {keywords_boost, keywords_ignore, min_score, source_whitelist}
  schedule         TEXT NOT NULL          -- cron, e.g. "0 8 * * *"
  channels_json    TEXT NOT NULL          -- [{type:"email", config:{to:"..."}}]
  format           TEXT NOT NULL DEFAULT 'digest'   -- digest | alert | summary
  enabled          INTEGER NOT NULL DEFAULT 1
  created_at       TEXT NOT NULL

article_scores                            -- per-(article, subscription) 评分
  article_id       TEXT NOT NULL          -- sha1(url)，与 Chroma article_id 一致
  subscription_id  INTEGER NOT NULL FK->subscriptions.id
  relevance_score  REAL NOT NULL
  summary          TEXT NOT NULL
  tags_json        TEXT NOT NULL
  key_insight      TEXT
  scored_at        TEXT NOT NULL
  PRIMARY KEY (article_id, subscription_id)

digests                                   -- 简报历史，供 Web 回看
  id               INTEGER PK
  subscription_id  INTEGER NOT NULL FK->subscriptions.id
  date             TEXT NOT NULL          -- YYYY-MM-DD
  content          TEXT NOT NULL          -- 已渲染的简报正文
  article_ids_json TEXT NOT NULL
  created_at       TEXT NOT NULL
  UNIQUE (subscription_id, date)
```

**职责切分**：Chroma 存全局文章向量 + 原始 metadata（一份）；SQLite 存用户/订阅/per-订阅评分/简报历史。`article_id = sha1(url)` 是两者的连接键，已在 Phase 2b 确立。

### Pydantic 模型（`src/radaragent/users/models.py`, `src/radaragent/subscriptions/models.py`）

- `User`, `UserCreate`（带明文密码，仅入参用）
- `Subscription`, `SubscriptionCreate`, `SubscriptionFilter`（pydantic 校验 cron / min_score 范围 / channels 结构）

---

## 二、认证（`src/radaragent/users/auth.py` + `sessions.py`）

- `hash_password(plain) -> str` / `verify_password(plain, hash) -> bool`：bcrypt。
- `register(db, email, password, output_language) -> User`：email 唯一性校验，密码强度下限（≥8 位）。
- `authenticate(db, email, password) -> User | None`。
- `SessionStore`：内存 + 可选 SQLite 落盘的 `token -> (user_id, expires_at)`；`create_session(user_id) -> token`、`resolve(token) -> user_id | None`、`revoke(token)`。
  - Phase 3 只暴露纯函数 / 类，**不绑定 HTTP**。Phase 4 的 FastAPI 中间件读 cookie → `SessionStore.resolve`。
  - token = `secrets.token_urlsafe(32)`，默认 30 天过期。

**首启引导**（`main.py`）：daemon 启动时若 `users` 表为空 → 命令行交互创建管理员（email + 密码 + output_language），并据旧 `interests.yaml`（若存在）生成一条默认订阅，然后**删除/归档** interests.yaml 的使用路径（不再读取它）。

---

## 三、处理层改造：per-subscription 评分

当前 `main.py` 的 sink：URL 去重 → 打分（全局 profile）→ 批量 embedding → 向量去重 → 存 Chroma → 打印。

Phase 3 改为：

```
plugin fetch → RawArticle[]
  └─ URL 去重（DedupChecker，全局）
  └─ 新文章：批量 embedding → 向量去重 → 存 Chroma（全局一份）
  └─ for each enabled subscription:
       for each new (non-dup) article:
         若 (article_id, sub_id) 已在 article_scores → skip
         LLM.score_and_summarize(article, sub.interest_profile, sub.filter, user.output_language)
         若 score >= sub.filter.min_score → 写 article_scores
```

**成本控制**：抓取共享（不变）；embedding 每篇一次（不变）；打分变成 文章×订阅 笛卡尔积——通过 `article_scores` 主键去重避免重复打分，且只对 `enabled` 订阅评分。早期单用户少订阅，成本可控；Phase 5 再做 batch / 缓存优化。

**LLM prompt 变化**：`interest_profile` 从全局 yaml 改为传入的订阅字段；`keywords_boost/ignore`、`min_score` 来自 `SubscriptionFilter`。`output_language` 来自订阅所属 `User`。

---

## 四、ServiceAPI（`src/radaragent/service/api.py`）

Facade，所有消费者（Phase 3 CLI、Phase 4 Web）共享，不直接耦合 RAG / 处理 / 调度。

```python
class ServiceAPI:
    def generate_digest(self, subscription_id: int, date: str) -> Digest
    async def query(self, user_id: int, question: str) -> Answer
    def search(self, user_id: int, filters: SearchFilters) -> list[ScoredArticle]   # Phase 3 签名预留，实现可滞后
```

- `generate_digest`：取该订阅当日 `article_scores` 高分文章（今日新增）+ 从 Chroma 按订阅 profile 语义检索 N 条历史上下文 → `LLMProvider.generate_digest(articles, context)` → 写 `digests` 表 → 返回。幂等：同 `(subscription_id, date)` 重跑覆盖。
- `query`：把 question embedding → Chroma 检索（限定该 user 订阅命中过的 article_id 集合）→ LLM 带检索上下文作答。范围隔离：用户只能问到自己订阅打过分的文章。
- `digest.py` / `query.py` 拆子模块，`api.py` 只做编排。

---

## 五、调度层改造（`src/radaragent/scheduler/`）

现状：`PluginScheduler` 每个 plugin 一个 cron job → sink。

新增 **digest job 维度**（保持插件 job 不变）：

- daemon 启动时：为每个 `enabled` 订阅按 `Subscription.schedule` `add_job` 一个 digest job → `ServiceAPI.generate_digest` → 遍历 channels → `EmailNotifier.send`。
- 订阅增删改 → 运行时 `add_job/remove_job`（Phase 4 Web 触发；Phase 3 提供 `reschedule(subscription_id)` 函数，CLI 可调）。
- 单订阅 digest 失败隔离：异常记录日志，不影响其他订阅 / 插件 job（沿用 Phase 2 的错误隔离原则）。

**CLI 补充触发**（`src/radaragent/output/cli.py` 或 main 子命令）：
- `radaragent run` — 启动 daemon（插件 job + 订阅 digest job 常驻）【首选路径】
- `radaragent digest --subscription <id> [--date YYYY-MM-DD]` — 一次性生成并推送
- `radaragent query --user <id> "问题"` — 一次性问答
- `radaragent useradd` — 手动建账号

---

## 六、推送层（`src/radaragent/providers/notifier/`）

- `Notifier` ABC：`async send(content: str, channel_config: dict) -> bool`。
- `EmailNotifier`：aiosmtplib，SMTP host/port/user/password/use_tls 从 `settings.yaml` 读；`channel_config` 提供收件人 `to`。HTML + 纯文本兼容多部分邮件。发送失败返回 False 并记日志，不抛断 digest job。

`settings.yaml` 新增：

```yaml
smtp:
  host: smtp.gmail.com
  port: 587
  username: ${SMTP_USERNAME}      # 从环境变量注入
  password: ${SMTP_PASSWORD}
  use_tls: true
  from_addr: radaragent@example.com
```

---

## 七、配置体系变化

- `config/interests.yaml`：**删除**。首启引导若检测到旧文件，提示用户其内容已迁移并据此建默认订阅，之后代码不再读取它。
- `config/settings.yaml`：移除 `interests` 相关；新增 `smtp`、`storage.sqlite_path`（默认 `data/radaragent.db`）、`auth.session_ttl_days`。
- `.gitignore` 确认含 `data/*.db`、`data/chroma`、`.env`。

---

## 八、目录结构（Phase 3 新增/变化）

```
src/radaragent/
├── storage/
│   ├── rag.py            (已有)
│   ├── dedup.py          (已有)
│   ├── models.py         (已有 RawArticle / ProcessedArticle)
│   └── db.py             (新) SQLite 连接 + schema migration + DAO
├── users/                (新)
│   ├── models.py         User / UserCreate
│   ├── auth.py           bcrypt + register/authenticate
│   └── sessions.py       SessionStore
├── subscriptions/        (新)
│   ├── models.py         Subscription / SubscriptionFilter
│   ├── crud.py           增删改查
│   └── scheduling.py     reschedule / per-sub job 注册
├── service/              (新)
│   ├── api.py            ServiceAPI facade
│   ├── digest.py         简报编排
│   └── query.py          RAG 问答编排
├── providers/notifier/   (新)
│   ├── base.py           Notifier ABC
│   └── email.py          EmailNotifier
├── scheduler/scheduler.py  (改) 增加 digest job 维度
├── output/cli.py         (新) CLI 子命令
└── main.py               (改) daemon 入口 + 首启引导 + 装配
```

---

## 九、测试策略

- `tests/test_storage/test_db.py`：schema 建表、DAO CRUD、唯一约束。
- `tests/test_users/`：bcrypt 往返、register 重复 email 拒绝、authenticate 正/误密码、SessionStore 过期。
- `tests/test_subscriptions/`：pydantic 校验（坏 cron / min_score 越界 / channels 结构）、crud。
- `tests/test_service/`：`generate_digest` 用 fake LLMProvider + 内存 Chroma 验证编排与幂等；`query` 范围隔离（用户问不到别人订阅的文章）。
- `tests/test_providers/test_email.py`：aiosmtplib mock，发送成功/失败返回值。
- 处理层 per-subscription 笛卡尔积去重：同文章同订阅不二次打分的回归测试。
- 不引入真实 SMTP / 真实 LLM；smoke test 仍可手动跑 `radaragent digest`。

---

## 十、待用户确认的开放问题

1. **首启引导交互**：daemon 第一次启动若 `users` 表空，是在终端阻塞式交互建管理员账号（适合首部署），还是只打印一条"请运行 `radaragent useradd`"然后退出？（倾向前者，更顺滑）
2. **`query` 检索范围**：是"该用户所有订阅命中过的文章"，还是"指定某个订阅范围内"？（倾向前者：用户全局问答更自然，Phase 4 再加按订阅过滤）
3. **`search` 接口**：Phase 3 是否需要可用实现，还是仅留签名占位到 Phase 4 随 Web 一起做？（倾向占位）
4. **digest 历史 RAG 上下文条数**：默认取多少条历史文章拼进简报 prompt（建议 5，settings 可配）？
5. **session 落盘**：内存 SessionStore 足够（daemon 重启需重新登录），还是 Phase 3 就落 SQLite（重启不掉线）？（单用户场景内存够用，倾向内存 + 留接口）

---

## 范围边界（明确不在 Phase 3）

- 任何 HTML / Jinja2 / FastAPI 路由 — Phase 4
- 飞书 / Telegram / Webhook Notifier — Phase 6
- 注册开放 / 配额 / 多语言 UI — Phase 7
- batch embedding / 缓存等性能优化 — Phase 5
- v0.1.0 → main 发布 — Phase 4 末（Web 上线后）
