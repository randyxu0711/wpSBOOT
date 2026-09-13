# wpSBOOT v2 進度紀錄

最後更新：2026-09-13

## 目前狀態

- 2019 年的 Flask 版已重寫為 v2：FastAPI + Postgres（資料庫兼 job queue）+ worker + Caddy，並用 docker compose 管理。
- 開發在 `v2` branch 上，**尚未 push，也尚未 merge 回 master**。舊版保留在 tag `v1-legacy`。
- 原訂計畫的里程碑 M0–M5 全部完成：
  - 工具鏈 image
  - 資料庫 / FASTA 驗證
  - pipeline 與 worker
  - API 與 `/admin`
  - 一頁式 RWD 前端
  - 正式部署設定、CI、部署手冊
- 66 個測試全部通過，其中包含在 container 裡實際執行 4 個 aligner 和 `concatenate.pl`。

## 已定案的決策

| 主題 | 決定 |
|---|---|
| 範圍 | 跟舊站一樣只產生 Super-MSA，論文的加權 bootstrap 不在本專案 |
| 實驗室工具 | `tools/concatenate.pl` **原封不動**，裝 BioPerl 後直接呼叫 |
| Aligner | MAFFT 7.525、MUSCLE 3.8.1551、ClustalW 2.1、T-Coffee 11.00、BioPerl 1.7.8（bioconda），指令參數沿用舊版 `wpSBOOT.sh` |
| 身分 | 免登入，結果網址用 UUID，最近的 job 記在瀏覽器 localStorage |
| 上限 | 200 條序列、單條 10,000、2 MB、job 30 分鐘、每 IP 每小時 10 個、保留 14 天，全部可用 `.env` 調整 |
| 序列名稱 | PHYLIP 會截成 10 字元（已實測）：截斷後撞名就擋下，只截斷或含特殊字元則警告 |
| 後台 | `/admin` 用 HTTP Basic，預設帳密 admin/admin（依需求設定；UI 與 log 都會警告） |
| 前端 | Jinja2 + vanilla JS，不用 SPA；沿用 #003752 / #8fcc52 與 logo |
| Git | commit 不加 Claude 署名 |

## 驗證過的項目

- 開發模式（:8000）與正式模式（Caddy HTTPS）都跑過完整流程：送出 → 執行 → 下載單檔與 zip → Mailpit 收到通知信
- 正式模式：HTTP 轉 HTTPS、安全 headers、CSP 下沒有任何被擋的資源、超過 4 MB 的上傳回 413、`/admin` 需要登入
- 備份與還原：照 `docs/deploy.md` 的指令實際操作過，資料筆數還原前後一致
- 瀏覽器截圖檢查桌機（1280px）與手機（390px），畫面沒有橫向捲動

## 還沒驗證

- GitHub Actions CI 還沒實際跑過（要 push 之後才會跑）
- 真實寄信服務（只測過 Mailpit）
- 真實網域的 Let's Encrypt 憑證（只測過 localhost）
- 在實際環境直接 kill worker container 後 job 是否被接手（只在測試中驗證）
- 大量或長序列時的執行時間，特別是 T-Coffee

## 待討論

1. **通知信功能**（下次優先討論）
   - 要不要保留這個功能？要的話 email 維持選填嗎？
   - 用哪種寄信方式：交易型寄信服務（Resend / Brevo / Mailgun / SES）、學校或系上的 SMTP relay，或其他。不建議自架 Postfix，也不建議用 Gmail。
   - 寄件網域與 SPF/DKIM 的設定由誰負責
   - 目前的做法：Python `smtplib` 透過標準 SMTP 寄出，相關設定都在 `.env` 的 `SMTP_*`；`SMTP_HOST` 留空就不寄信（網頁上的 email 欄位會自動隱藏）；寄完後會從資料庫刪除 email 地址
2. 是否要加 `./setup.sh`，互動式產生 `.env`（先不急）
3. 部署主機與網域
4. 跟實驗室確認聯絡資訊，以及是否要加 LICENSE

## 待辦（使用者）

- [ ] 舊的 Gmail 帳號 `wpsboot@gmail.com` 改密碼或停用（密碼留在公開的 git history 裡）
- [ ] 本機測試各項功能
- [ ] 上線前把 `ADMIN_PASSWORD` 改掉
- [ ] 確認沒問題後，merge `v2` 回 master 並 push

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
