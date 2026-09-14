# wpSBOOT v2 進度紀錄

最後更新：2026-09-14

## 目前狀態

- 2019 年的 Flask 版已重寫為 v2：FastAPI + Postgres（資料庫兼 job queue）+ worker + Caddy，並用 docker compose 管理。
- 2026-09-14 已 push 並 fast-forward merge 回 master，GitHub Actions CI 在 `v2` 與 `master` 都通過。之後繼續在 `v2` 開發。舊版保留在 tag `v1-legacy`（已 push）。
- 原訂計畫的里程碑 M0–M5 全部完成：
  - 工具鏈 image
  - 資料庫 / FASTA 驗證
  - pipeline 與 worker
  - API 與 `/admin`
  - 一頁式 RWD 前端
  - 正式部署設定、CI、部署手冊
- 74 個測試全部通過，其中包含在 container 裡實際執行 4 個 aligner 和 `concatenate.pl`。
- 2026-09-14 做過一次安全審查並修正（見下方「安全審查」）。目前沒有上線計畫，防護做到合理程度即可。

## 已定案的決策

| 主題 | 決定 |
|---|---|
| 範圍 | 跟舊站一樣只產生 Super-MSA，論文的加權 bootstrap 不在本專案 |
| 實驗室工具 | `tools/concatenate.pl` **原封不動**，裝 BioPerl 後直接呼叫 |
| Aligner | MAFFT 7.525、MUSCLE 3.8.1551、ClustalW 2.1、T-Coffee 11.00、BioPerl 1.7.8（bioconda），指令參數沿用舊版 `wpSBOOT.sh` |
| 身分 | 免登入，結果網址用 UUID，最近的 job 記在瀏覽器 localStorage |
| 上限 | 200 條序列、單條 10,000、2 MB、job 30 分鐘、每 IP 每小時 10 個、每 IP 同時最多 2 個排隊或執行中（IPv6 以 /64 計）、保留 14 天，全部可用 `.env` 調整 |
| 序列名稱 | PHYLIP 會截成 10 字元（已實測）：截斷後撞名就擋下，只截斷或含特殊字元則警告 |
| 後台 | `/admin` 用 HTTP Basic，預設帳密 admin/admin（依需求設定；UI 與 log 都會警告） |
| 前端 | Jinja2 + vanilla JS，不用 SPA；沿用 #003752 / #8fcc52 與 logo |
| Git | commit 不加 Claude 署名 |

## 驗證過的項目

- 開發模式（:8000）與正式模式（Caddy HTTPS）都跑過完整流程：送出 → 執行 → 下載單檔與 zip → Mailpit 收到通知信
- 正式模式：HTTP 轉 HTTPS、安全 headers、CSP 下沒有任何被擋的資源、超過 4 MB 的上傳回 413、`/admin` 需要登入
- 備份與還原：照 `docs/deploy.md` 的指令實際操作過，資料筆數還原前後一致
- 瀏覽器截圖檢查桌機（1280px）與手機（390px），畫面沒有橫向捲動

## 安全審查（2026-09-14）

沒有發現問題：command injection（不經 shell）、路徑穿越、SQL injection、XSS、CSRF、email header injection。

已修正：
- 每個 IP 同時排隊或執行中的 job 上限（`MAX_ACTIVE_JOBS_PER_IP`，預設 2），IPv6 以 /64 計算，避免一個人佔滿所有 worker
- aligner 只繼承 `PATH`、`LANG`、`LC_ALL`、`TZ`，拿不到資料庫與後台密碼
- 序列 header 含控制字元時回 422（原本 NUL 字元會造成 500）
- 前端把貼上的序列以檔案形式送出（表單欄位原本被框架限制在 1 MB）
- web / worker 加上 `cap_drop: ALL`、`no-new-privileges`，worker 限制 512 個 process

刻意不做：
- 資料庫改用非 superuser 角色（攻擊前提是 aligner 被攻破，且沒有上線計畫）
- 後台登入失敗次數限制、持有結果網址即可刪除 job（屬於設計取捨）

## 還沒驗證

- 正式環境的反向代理後面，app 看到的是否是使用者的真實 IP（本機 dev 模式全部顯示為 Docker gateway，會讓所有人共用 rate limit 額度）
- 真實寄信服務（只測過 Mailpit）
- 真實網域的 Let's Encrypt 憑證（只測過 localhost）
- 在實際環境直接 kill worker container 後 job 是否被接手（只在測試中驗證）
- 大量或長序列時的執行時間，特別是 T-Coffee

## 待討論

目前沒有上線計畫，以下都等到要用時再決定：

1. **通知信**：程式保留、預設關閉。要啟用時先問系上有沒有 SMTP relay，沒有再考慮 Resend / Brevo 等交易型寄信服務（不建議 Gmail 或自架 Postfix）。設定都在 `.env` 的 `SMTP_*`。
2. 部署主機與網域（部署指令已寫在 README，會自動產生隨機密鑰與 admin 密碼）
3. 跟實驗室確認聯絡資訊，以及是否要加 LICENSE
4. 資料庫改用非 superuser 角色（見「安全審查」）

已決定不做：`./setup.sh`（README 的複製貼上指令已涵蓋）、舊 Gmail 帳號 `wpsboot@gmail.com` 不處理（當作歷史遺跡）。

## 待辦

- [x] 本機測試各項功能（sample、後台）
- [x] merge `v2` 回 master 並 push，CI 通過
- [ ] 真的要上線時：確認 `ADMIN_PASSWORD` 不是預設值、確認拿得到使用者真實 IP

## 本機操作速查

```sh
cd ~/projects/wpSBOOT
docker compose up -d        # .env 裡已設定 COMPOSE_FILE，會以開發模式啟動
docker compose down         # 停止並移除 container，資料保留在 volume
```

| 網址 | 內容 |
|---|---|
| http://localhost:8000 | 網站 |
| http://localhost:8000/admin | 後台（admin / admin） |
| http://localhost:8000/api/docs | API 文件 |
| http://localhost:8025 | Mailpit 假信箱 |

- 正式模式：在 VS Code 對 `compose.yaml` 按右鍵 → Compose Up，網址是 https://localhost。兩種模式不要同時開。
- 容器內跑全部測試：`COMPOSE_FILE=compose.yaml docker compose --profile test run --rm --build test`
- 開發者說明見 `README.md`，部署說明見 `docs/deploy.md`

## 開發環境注意事項

- Docker Desktop 要開啟這個 WSL distro 的 integration；剛開啟時可能需要重啟 Docker Desktop，`/var/run/docker.sock` 才會出現。
- 第一次 build worker image 要從 conda 下載約 300 MB，網路慢時可能逾時，Dockerfile 已加入 cache 與自動重試。
- Postgres 在開發模式開放於 `127.0.0.1:55432`。
