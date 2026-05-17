# 部署（VPS + Docker + Caddy）

RadarAgent 单进程同时跑调度器和 Web（`radaragent run` 内置 uvicorn）。生产栈两个容器：

- `app` — 守护进程 + FastAPI（监听容器内 `8000`，不直接暴露）
- `caddy` — 反向代理，自动申请/续期 Let's Encrypt 证书，对外 `80/443`

## 1. 前置

- 一台公网 VPS（1C2G 起步即可，**无 GPU**）
- 一个解析到该 VPS 的域名（A 记录指向 VPS IP）
- 已装 Docker + Docker Compose 插件

## 2. 拉取代码 + 配置

```bash
git clone https://github.com/SherlockDavis/RadarAgent.git
cd RadarAgent
cp .env.example .env
```

编辑 `.env`：

- `RADAR_DOMAIN` = 你的域名（Caddy 用它签证书）
- `DEEPSEEK_API_KEY`（或你在 `settings.yaml` 选用的 LLM key）
- 需要邮件推送则填 `SMTP_USERNAME` / `SMTP_PASSWORD`
- CPU VPS 见下方「embedding」一节，可能需要 `OPENAI_API_KEY`

编辑 `config/settings.yaml`：

- **embedding**：默认 `provider: local` + `device: cuda` 是给有 GPU 的开发机用的，
  镜像里**不装 torch/bge-m3**。CPU VPS 改为：
  ```yaml
  embedding:
    provider: openai
    model: text-embedding-3-small
    api_key: ${OPENAI_API_KEY}
  ```
  （或自建 OpenAI 兼容 embedding 端点，填 `base_url`）
- **web.cookie_secure**：反代终止 TLS 后改 `true`，session cookie 只走 HTTPS：
  ```yaml
  web:
    cookie_secure: true
  ```

`docker-compose.yaml` 已把 `./config` 只读挂载、`./data`（SQLite + Chroma）持久化挂载。

## 3. 创建管理员账号

首次以 detached 启动没有 TTY，守护进程不会交互建号。两种方式任选：

- 一次性交互容器：
  ```bash
  docker compose run --rm app radaragent useradd
  ```
- 或先 `up`（见下一步）后直接访问 `https://<域名>/register`，
  **第一个注册的账号自动成为管理员**。

## 4. 启动

```bash
docker compose up -d --build
docker compose logs -f app
```

Caddy 会在首次请求时自动签发证书。打开 `https://<RADAR_DOMAIN>/` 即进入登录页。

健康检查：容器内 `GET /healthz`；外部 `https://<域名>/healthz` 应返回
`{"status":"ok"}`。

## 5. 运维

- 升级：`git pull && docker compose up -d --build`
- 备份：整个 `./data/` 目录（`radaragent.db` + `chroma/`）
- 日志：`docker compose logs -f app` / `caddy`
- 改订阅/调度：在 Web 里改即可，调度器进程内实时 reschedule，无需重启
- 改 `settings.yaml` / `.env`：`docker compose up -d`（重建受影响容器）

## 6. 故障排查

| 现象 | 排查 |
|---|---|
| 证书签发失败 | 域名 A 记录是否指向本机；`80/443` 是否被占用/防火墙放行 |
| 登录后立刻退出 | `web.cookie_secure: true` 但走的是 HTTP——用 HTTPS 域名访问 |
| 启动报缺 torch | embedding 仍是 `provider: local`，按第 2 步改 openai |
| `/register` 提示已注册 | 账号已存在，去 `/login` |
