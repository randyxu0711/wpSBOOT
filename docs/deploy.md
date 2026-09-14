# wpSBOOT 部署與維運手冊

這份文件從一台全新的 Linux 主機開始，一步步把 wpSBOOT 部署成對外服務，並涵蓋日常維運、更新、備份還原與疑難排解。

---

## 1. 需求

| 項目 | 建議 |
|---|---|
| 主機 | x86_64（amd64）Linux，例如 Ubuntu 22.04/24.04。**不支援 ARM**：舊版 MUSCLE 3.8 沒有 ARM 版本 |
| 規格 | 2 vCPU / 4 GB RAM 起跳，可跑 2 個 worker；硬碟 20 GB 以上 |
| 軟體 | Docker Engine 24 以上，並安裝 Compose v2 plugin（`docker compose version` 能正常執行） |
| 網路 | 對外開放 TCP 80、443（HTTP/3 另需 UDP 443） |
| 網域 | 一個 DNS A 紀錄指向主機 IP，例如 `wpsboot.example.org` |
| 寄信（選用） | 學校或實驗室的 SMTP，或 Resend / Mailgun / AWS SES 等交易型寄信服務 |

第一次 build 時，worker image 需要從 conda 下載約 300 MB 的套件，網路慢的話可能要 10 分鐘以上。

## 2. 取得程式碼

```sh
git clone https://github.com/randyxu0711/wpSBOOT.git
cd wpSBOOT
git checkout master     # 或要部署的 tag / branch
```

## 3. 設定 `.env`

```sh
cp .env.example .env
chmod 600 .env
```

用下列指令產生隨機值：

```sh
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

**必改項目**

| 變數 | 說明 |
|---|---|
| `DOMAIN` | 對外網域，例如 `wpsboot.example.org`。Caddy 會自動向 Let's Encrypt 申請憑證 |
| `PUBLIC_BASE_URL` | `https://` 加上網域，用於產生通知信裡的連結 |
| `SECRET_KEY` | 隨機字串，至少 16 字元。沿用 `change-me` 或長度不足時，服務會拒絕啟動 |
| `POSTGRES_PASSWORD` | 資料庫密碼，填隨機字串。**第一次啟動後就不要再改**（詳見疑難排解） |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | `/admin` 的帳密。**預設是 admin/admin，一定要改**；留空 `ADMIN_PASSWORD` 則關閉後台 |

**寄信（選用）**：`SMTP_HOST` 留空就不寄信，網頁上的 email 欄位也會自動隱藏。

```
SMTP_HOST=smtp.example.org
SMTP_PORT=587
SMTP_SECURITY=starttls        # 465 port 用 ssl
SMTP_USERNAME=...
SMTP_PASSWORD=...
MAIL_FROM="wpSBOOT <noreply@wpsboot.example.org>"
```

寄件網域要設定 SPF 與 DKIM（依寄信服務的說明新增 DNS 紀錄），否則信件很容易被當成垃圾信。

**容量與上限**：`WORKER_REPLICAS`、`WORKER_CPUS`、`WORKER_MEMORY`、`MAX_SEQUENCES`、`JOB_TIMEOUT_SECONDS`、`RETENTION_DAYS`、`RATE_LIMIT_PER_HOUR`、`MAX_ACTIVE_JOBS_PER_IP` 等，預設值見 `.env.example`。每個 worker 一次處理一個 job，job 內的 aligner 會平行執行，所以 `WORKER_REPLICAS × WORKER_CPUS` 不應超過主機的 CPU 數。

> ⚠️ 正式主機的 `.env` **不要**設定 `COMPOSE_FILE`。那是本機開發用的，會啟用 hot reload 並開放不必要的 port。

## 4. 啟動

```sh
docker compose up -d --build
docker compose ps
```

正常狀態：`db`、`web`、`worker`（N 個）顯示 `healthy`，`caddy`、`backup` 為 `Up`，`migrate` 為 `Exited (0)`（它只負責跑一次資料庫 migration）。

驗證：

```sh
curl -I https://wpsboot.example.org/healthz            # 200
docker compose logs caddy | grep -i "certificate obtained"
```

用瀏覽器打開網站，點「Load sample sequences」→「Build Super-MSA」，大約 10 秒內應該跑完，並能下載 zip。

## 5. 日常維運

| 要做的事 | 指令 |
|---|---|
| 看 log | `docker compose logs -f web worker` |
| 看最近的錯誤 | `docker compose logs --since 1h worker \| grep -E "ERROR\|WARNING"` |
| Job 管理 | 瀏覽器開 `https://<網域>/admin`：可篩選、看每個步驟的 stderr、取消、刪除、重新執行失敗的 job |
| 調整 worker 數量 | 修改 `.env` 的 `WORKER_REPLICAS` 後執行 `docker compose up -d` |
| 重啟服務 | `docker compose restart web worker` |
| 停止全部 | `docker compose down`（資料保存在 volume，不會遺失） |

Worker 收到停止訊號時，會把正在跑的 job 放回 queue，下次啟動時重新執行。Worker 若異常中斷，約 2 分鐘後其他 worker 會把 job 接手；同一個 job 連續中斷 2 次就標記為失敗。

## 6. 更新版本

```sh
git pull
docker compose up -d --build
```

資料庫 migration 會由 `migrate` 服務自動執行。更新前建議先手動備份一次（見下節）。

## 7. 備份與還原

`backup` 服務每天把資料庫 dump 到 `backups` volume，保留最近 `BACKUP_KEEP` 份（預設 7）。Job 檔案本來就只保留 `RETENTION_DAYS` 天，所以不另外備份。

**列出與取出備份**

```sh
docker compose exec backup ls -lh /backups
docker compose cp backup:/backups/wpsboot-20260913T000000Z.sql.gz ./
```

**立即手動備份**

```sh
docker compose exec -T db pg_dump -U wpsboot --no-owner wpsboot | gzip > wpsboot-manual.sql.gz
```

**還原**（會覆蓋現有資料）

```sh
docker compose stop web worker
docker compose exec -T db psql -U wpsboot -d postgres -c "DROP DATABASE wpsboot WITH (FORCE)" -c "CREATE DATABASE wpsboot"
gunzip -c wpsboot-20260913T000000Z.sql.gz | docker compose exec -T db psql -U wpsboot -d wpsboot
docker compose up -d
```

建議定期把備份檔複製到主機以外的地方。

## 8. 安全檢查清單

- [ ] `ADMIN_PASSWORD` 已改掉預設的 admin（`/admin` 頁面頂端不再出現紅色警告）
- [ ] `SECRET_KEY`、`POSTGRES_PASSWORD` 都是隨機字串，`.env` 權限為 600
- [ ] 防火牆只開 22、80、443；Postgres 沒有對外開放（正式設定本來就不會開 port）
- [ ] 主機的系統更新與 Docker 版本保持更新
- [ ] 舊版 repo 的 git history 裡有 Gmail 帳號 `wpsboot@gmail.com` 的密碼，該帳號已改密碼或停用

## 9. 疑難排解

| 狀況 | 可能原因與處理 |
|---|---|
| `web` 一直重啟，log 出現 `SECRET_KEY must be...` | `.env` 的 `SECRET_KEY` 沒改或太短 |
| 網站打不開、Caddy log 出現 ACME 錯誤 | DNS 還沒生效，或 80/443 被防火牆擋住。Let's Encrypt 必須能從外部連到 80 port |
| `migrate` 失敗、出現 `password authentication failed` | 第一次啟動後才修改 `POSTGRES_PASSWORD`。資料庫只在第一次建立時讀這個值，請改回原本的密碼，或用 `ALTER USER wpsboot PASSWORD '...'` 同步修改 |
| Job 一直停在 queued | 用 `docker compose ps worker` 確認 worker 有在跑，並查看 `docker compose logs worker` |
| 某個 aligner 常常 `time limit exceeded` | 序列太多或太長。可調高 `JOB_TIMEOUT_SECONDS`、`WORKER_CPUS`，或調低 `MAX_SEQUENCES` |
| 上傳顯示 413 | 超過大小上限：Caddy 限制 4 MB，應用程式預設限制 2 MB（`MAX_UPLOAD_BYTES`） |
| 沒收到通知信 | 在 `/admin` 的 job 詳細頁看「Notified」欄位，並用 `docker compose logs worker \| grep notification` 查看寄信錯誤 |
| 硬碟空間不足 | `docker system df` 查看用量，`docker image prune` 清掉舊 image；job 檔案會依 `RETENTION_DAYS` 自動刪除 |
