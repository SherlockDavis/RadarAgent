# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial project scaffolding: CLAUDE.md, design spec, repository configuration files
- MIT License
- Conventional Commits + branch strategy + PR template
- pre-commit configuration (ruff / mypy / commitlint)
- GitHub Actions CI workflow scaffold
- Local SSH commit signing configuration
- Phase 1 MVP source layout: `src/radaragent/` package
- Data models: `RawArticle`, `ProcessedArticle`
- `SourcePlugin` base class + plugin registry
- `RSSPlugin` (generic RSS / Atom reader)
- `LLMProvider` base + `OpenAILLMProvider` (score, digest, embed)
- `PluginScheduler` (APScheduler-backed, cron triggers, error isolation)
- Config loader with `${VAR}` env-var expansion (pydantic-validated)
- Default `config/settings.yaml` + `config/interests.yaml` + `.env.example`
- CLI entry: `radaragent` with `--once` smoke mode

[Unreleased]: https://github.com/Sherlock/RadarAgent/compare/HEAD
