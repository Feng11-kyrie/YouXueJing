# 优学鲸 · 上线部署手册（Docker + Caddy）

目标：把优学鲸放到一台 24 小时在线的云服务器上，别人通过 HTTPS 打开。
推荐顺序：**Oracle Always Free（¥0）→ 低价 VPS（¥100–250/年）**。
不推荐 Vercel/Netlify/Streamlit Cloud：NiceGUI 需要 WebSocket + 本地 SQLite。

---

## 0. 文件说明

| 文件 | 作用 |
|---|---|
| `Dockerfile` | Python 3.12 + NiceGUI 运行环境 |
| `requirements-prod.txt` | 生产依赖（不含 Streamlit/LangGraph） |
| `docker-compose.yml` | app + Caddy 两个容器，单实例 |
| `Caddyfile` | 自动 HTTPS / WebSocket 反代 |
| `.env.example` | `YJ_SECRET` 与 `DOMAIN` |
| `scripts/backup.sh` | SQLite 热备份 + 题库打包，保留 14 天 |

`data/` 不在 Git 里，部署时必须单独上传（约 46MB）。

---

## 1. 服务器

### 方案 A：Oracle Always Free（¥0）

1. 注册 Oracle Cloud，创建 **Ampere A1 / Ubuntu 24.04** 实例；
   建议 2 OCPU / 8GB 起（4/24 也可以，但别超 Always Free 额度）。
2. 分配公网 IPv4。
3. 在 VCN 安全列表放行 **80、443**（不要放行 8080）。
4. 记住公网 IP。

### 方案 B：低价 VPS（¥100–250/年）

- 香港/新加坡 1C1G 或 2C2G，Ubuntu 24.04；
- 放行 80/443；
- 不买域名也能用 `sslip.io`。

---

## 2. 安装 Docker

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-v2 rsync
sudo usermod -aG docker $USER   # 重新登录后生效
```

国内服务器如果拉不到 Docker Hub，先配镜像，或手动拉取后改标签：

```bash
docker pull docker.m.daocloud.io/library/python:3.12-slim
docker tag docker.m.daocloud.io/library/python:3.12-slim python:3.12-slim

docker pull docker.m.daocloud.io/library/caddy:2
docker tag docker.m.daocloud.io/library/caddy:2 caddy:2
```

---

## 3. 上传项目（含 data）

在 Mac 上执行（把 IP 换成服务器 IP）：

```bash
rsync -av --delete \
  --exclude '.venv' --exclude '.git' --exclude '_shots' \
  --exclude '.nicegui' --exclude 'backups' \
  ./ root@<服务器IP>:/opt/youxuejing/
```

确认服务器上存在：

```bash
ls /opt/youxuejing/data/yj.db
ls /opt/youxuejing/proto/app.py
```

---

## 4. 配置并启动

```bash
cd /opt/youxuejing
cp .env.example .env
# 生成强随机密钥（不要用默认值）
sed -i "s|replace-with-a-long-random-secret|$(openssl rand -hex 32)|" .env
# 没有域名：用 sslip.io，把 IP 改成服务器公网 IP
sed -i "s|app.1.2.3.4.sslip.io|app.<服务器IP>.sslip.io|" .env

docker compose up -d --build
docker compose ps
docker compose logs -f caddy
```

打开：

- 有域名：`https://你的域名`
- 无域名：`https://app.<服务器IP>.sslip.io`

首次访问如果证书还没签发，等 1–2 分钟。

> 8080 只在 Docker 内网暴露，公网只开 80/443。

---

## 5. 首次登录

- 打开 `/register` 注册第一个账号；
- 或点「游客体验」看 demo 数据；
- 确认 `/login`、注册、做题、诊断、错题本都能用。

---

## 6. 备份

```bash
chmod +x scripts/backup.sh
scripts/backup.sh
crontab -e
```

加一行（每天 03:00）：

```cron
0 3 * * * /opt/youxuejing/scripts/backup.sh >> /var/log/yj-backup.log 2>&1
```

建议再把 `backups/` 同步到 Mac 或对象存储；只留服务器本地不算备份。

---

## 7. 更新版本

```bash
# Mac 上重新 rsync（保留服务器 data 不动）
rsync -av --delete --exclude '.venv' --exclude '.git' \
  --exclude '_shots' --exclude '.nicegui' --exclude 'backups' \
  ./ root@<服务器IP>:/opt/youxuejing/

# 服务器
cd /opt/youxuejing
docker compose up -d --build
```

`./data` 是挂载卷，更新代码不会覆盖数据库。

---

## 8. 注意

- **只能单实例**：NiceGUI 有进程内会话，SQLite 也不适合多副本；
- **YJ_SECRET 不要改**：改了所有登录会话失效；
- **不要把 8080 暴露公网**；
- Oracle 免费机可能被回收：务必每日备份，保留重建步骤；
- 上线前建议先补：找回密码、登录限流、隐私政策/用户协议；
- 真题/解析公开分发有版权风险，先小范围邀请制更稳妥。
