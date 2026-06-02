# Deploy — HTTPS via Cloudflare Tunnel（tantai.xyz）· AS-BUILT

> 状态：**已上线并端到端验证（2026-06-02）**。本文是实况记录 + 可复现 runbook（已按真实执行校准，非计划稿）。
> 目标一次解决三件事：① 复制/下载所需的"安全上下文"（`navigator.clipboard` / `showSaveFilePicker` 仅 HTTPS/localhost 可用）；② GitHub webhook 跨境 502；③ 合法 HTTPS 证书。
> 方案：**Cloudflare Tunnel（cloudflared，locally-managed + config.yml）**。复用现有 `/home/tbx/codessentinel` 部署，不买新服务器、不迁移。

---

## 0. 关键事实（照抄，别凭印象）

| 项 | 值 |
|---|---|
| 域名 | `tantai.xyz`（Spaceship 注册，NS 托管 Cloudflare 免费版，自动续约关，到期 2027-06-02） |
| 站点 | 根域 `https://tantai.xyz` |
| 服务器 | `tbx@115.190.51.187`（Ubuntu 22.04 / amd64），sudo 需密码 |
| 项目目录 | `/home/tbx/codessentinel`（`docker-compose.prod.yml`） |
| 隧道 | name `codesentinel`，ID `56125224-3f6f-4cb0-872c-aaa4f88746b6` |
| 路由 | `^/(api|ws)/` → `localhost:8000`（后端+WS）；其余 → `localhost:5173`（前端） |

**真实路由前缀**（来源 backend 代码，配 ingress 用）：API/webhook 在 `/api/v1/...`（webhook=`/api/v1/webhooks/github`）；**WebSocket 在根 `/ws/{review_id}`，不在 /api/v1 下**——所以 ingress 正则必须 `^/(api|ws)/` 同时放行两者。改路由前缀记得同步这里。

---

## Part A — 接入 Cloudflare（浏览器，已完成）

1. dash.cloudflare.com 注册 → Connect a domain → `tantai.xyz` → Free。
2. "Review your DNS records" 页 **0 条记录直接 Continue to activation**（MX/www/根 A 警告忽略：隧道会自动建所需 DNS）。
3. 拿到两条 nameserver（本次 `emely.ns.cloudflare.com` / `lars.ns.cloudflare.com`）。
4. Spaceship → tantai.xyz → Nameservers 改 Custom 填这两条 → 保存。
5. 等 Cloudflare Overview 显示绿色 **Active**（本次约数十分钟）。

---

## Part B — 服务器配隧道（已完成）

### B1. 装 cloudflared —— ⚠️ 不能用 github releases 的 .deb
本服务器**直连不上 github.com**，故走 Cloudflare 官方 apt 源（`pkg.cloudflare.com` 可达）：
```bash
sudo curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg -o /usr/share/keyrings/cloudflare-main.gpg
echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared jammy main" | sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt-get update && sudo apt-get install -y cloudflared
```

### B2. `cloudflared tunnel login` —— ⚠️ 证书回传跨境失败，必须走本地代理
直连时 login 末尾从 `login.cloudflareaccess.org` 拉证书会 `Failed to fetch resource`（跨境）。解法=**用 SSH 反向隧道把本地 Clash 代理(7890)映射到服务器**，只在这一次性步骤用：
```bash
# 在本机发起（-R 把本地 7890 映射到服务器 127.0.0.1:17890）：
ssh -R 127.0.0.1:17890:127.0.0.1:7890 tbx@115.190.51.187 \
  "https_proxy=http://127.0.0.1:17890 http_proxy=http://127.0.0.1:17890 cloudflared tunnel login"
# 浏览器打开打印的 URL → 选 tantai.xyz → Authorize → 证书经代理落地 ~/.cloudflared/cert.pem
```

### B3. 建隧道 + 配置 + 绑 DNS（create/route 也经代理调 API）
```bash
# 经同一反向隧道执行：
https_proxy=http://127.0.0.1:17890 cloudflared tunnel create codesentinel
# 写 ~/.cloudflared/config.yml：
#   tunnel: <ID>
#   credentials-file: /home/tbx/.cloudflared/<ID>.json
#   ingress:
#     - hostname: tantai.xyz
#       path: ^/(api|ws)/
#       service: http://localhost:8000
#     - hostname: tantai.xyz
#       service: http://localhost:5173
#     - service: http_status:404
https_proxy=http://127.0.0.1:17890 cloudflared tunnel route dns codesentinel tantai.xyz
```

### B4. 持久化为 systemd 服务（root；隧道 run 本身直连边缘，不需代理）
```bash
sudo mkdir -p /etc/cloudflared
sudo cp ~/.cloudflared/config.yml /etc/cloudflared/config.yml
sudo cp ~/.cloudflared/<ID>.json /etc/cloudflared/
sudo sed -i 's#/home/tbx/.cloudflared/#/etc/cloudflared/#' /etc/cloudflared/config.yml   # 凭据路径同步
sudo cloudflared service install
sudo systemctl enable --now cloudflared
systemctl is-active cloudflared        # active；journalctl -u cloudflared 见 "Registered tunnel connection" x4 (QUIC)
```
> 实测隧道 run **不依赖代理**直连 sjc QUIC 边缘（precheck: Environment is healthy）。代理只在 B2/B3 一次性 login/API 用过。

---

## Part C — 应用侧改造（已完成）

服务器 `/home/tbx/codessentinel/.env`（已备份 `.env.bak.https`）：
```
PUBLIC_API_URL=https://tantai.xyz
PUBLIC_WS_URL=wss://tantai.xyz
CORS_ORIGINS=https://tantai.xyz,http://115.190.51.187:5173
```
```bash
docker compose -f docker-compose.prod.yml up -d --build frontend          # VITE 烘焙新地址（bundle 实测旧 IP 残留 0）
docker compose -f docker-compose.prod.yml up -d --force-recreate backend   # 重载 CORS
```
**GitHub Webhook**：`Lupinusluv/Demonstration` → Settings → Webhooks → Payload URL 改 `https://tantai.xyz/api/v1/webhooks/github`（Content-Type json，Secret 不变）。

---

## Part D — 验收（2026-06-02 全部通过）

- [x] `https://tantai.xyz/` 合法证书、HTTP 200，控制台 0 报错。
- [x] 浏览器 `isSecureContext=true`、`navigator.clipboard` 与 `showSaveFilePicker` 均可用 → **AutoFix 复制/下载随之修复**。
- [x] `GET /api/v1/health` → 200，`wss://tantai.xyz/ws/...` 升级 OPEN。
- [x] GitHub webhook redeliver → **202**（不再 502）→ 后端入队 → 三 Agent → synthesis → 回写 commit status(failure)+PR 评论，10.5s 全链路。

---

## 备注 / 坑

- github.com 服务器仍直连不上；cloudflared 走 pkg.cloudflare.com apt 源（不碰 github）。
- login/create/route 的跨境 API 调用需经本机代理（SSH `-R` 反向隧道）；**隧道长期运行不需要**。
- QUIC 启动有 `failed to sufficiently increase receive buffer size` WARN，无害；如要消除可调 `net.core.rmem_max`。
- 可选安全收敛：隧道稳定后对公网关闭入站 8000/5173（仅留 SSH + 隧道出站），保留 SSH 端口别锁死自己。
- 运维硬知识另见记忆 [[project_deploy_notes]]。
