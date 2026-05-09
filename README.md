# RadarAgent

> 一个领域无关的 24 小时情报系统框架

给定一组数据源、一份用户兴趣描述和一个推送渠道，RadarAgent 持续抓取多语言信息、由 LLM 过滤打分、构建可语义检索的知识库，并按计划生成简报推送给用户。

无论你关注技术、金融、学术、行业新闻还是其他领域，RadarAgent 通过插件化数据源、可配置的兴趣 profile、可替换的 LLM 与推送 Provider，让你用一份配置就能搭起自己的领域 radar。

**状态**：Phase 0（项目骨架搭建中）

## 特性




## 项目文档

- [`CLAUDE.md`](./CLAUDE.md) —— 项目核心契约与架构
- [`docs/superpowers/specs/`](./docs/superpowers/specs/) —— 详细设计文档
- [`docs/plugins.md`](./docs/plugins.md) —— 如何编写新数据源插件（待补）
- [`docs/providers.md`](./docs/providers.md) —— 如何实现 LLMProvider / Notifier（待补）

## 贡献

提交规范遵循 [Conventional Commits](https://www.conventionalcommits.org/)。
所有变更通过 PR 合入；禁止直接 push 到 `main` / `develop`。
详见 [`CLAUDE.md` 的 Git 工作流章节](./CLAUDE.md#git-工作流)。

## License

[MIT](./LICENSE) © 2026 Sherlock
