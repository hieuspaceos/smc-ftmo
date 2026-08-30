# Cloudflare Tunnel + Cloudflare Access Setup

> Hướng dẫn expose webhook + admin dashboard ra internet qua Cloudflare Tunnel (free) + bảo vệ admin pages bằng Cloudflare Access (free).

## Tại sao Cloudflare Tunnel?

- **Free**: không cần VPS, không cần domain riêng (dùng `*.trycloudflare.com`)
- **HTTPS automatic**: TradingView webhook yêu cầu HTTPS 443
- **No port forwarding**: local FastAPI + Streamlit bind localhost, tunnel route ra ngoài
- **IP allowlist không cần**: TradingView IPs luôn từ Cloudflare edge

## Setup Steps

### 1. Cài cloudflared (macOS)

```bash
brew install cloudflared
```

### 2. Quick tunnel (URL random mỗi restart)

```bash
# Chạy FastAPI local
uvicorn bot.webhook.server:app --host 127.0.0.1 --port 8000 &

# Chạy Streamlit local
streamlit run bot/dashboard/streamlit_app.py --server.port 8501 &

# Expose cả 2 qua Cloudflare quick tunnel
cloudflared tunnel --url http://localhost:8000  # webhook
cloudflared tunnel --url http://localhost:8501  # dashboard
```

Lưu ý: quick tunnel URL sẽ đổi mỗi lần restart. Mỗi lần restart phải update TradingView alert URL.

### 3. Named tunnel (stable URL — khuyến nghị)

```bash
# Login Cloudflare account
cloudflared tunnel login

# Tạo tunnel
cloudflared tunnel create smc-bot

# Tạo config file ~/.cloudflared/config.yml
cat > ~/.cloudflared/config.yml <<EOF
tunnel: smc-bot
credentials-file: /Users/<you>/.cloudflared/<tunnel-id>.json

ingress:
  - hostname: webhook.your-domain.com
    service: http://localhost:8000
  - hostname: admin.your-domain.com
    service: http://localhost:8501
  - service: http_status:404
EOF

# Route DNS
cloudflared tunnel route dns smc-bot webhook.your-domain.com
cloudflared tunnel route dns smc-bot admin.your-domain.com

# Run
cloudflared tunnel run smc-bot
```

Yêu cầu: domain owned by bạn + add vào Cloudflare (free plan OK).

### 4. Cloudflare Access (admin protection)

Vào Cloudflare Zero Trust dashboard → Access → Applications:

#### Application 1: Webhook (no auth, public)
- Name: `SMC Bot Webhook`
- Domain: `webhook.your-domain.com`
- Policy: **Allow** without identity (public, cho TradingView POST)

#### Application 2: Admin Dashboard (auth required)
- Name: `SMC Bot Admin`
- Domain: `admin.your-domain.com`
- Policy: **Allow** with:
  - Emails: `[your-email@example.com]`
  - 2FA: required
  - Session duration: 24 hours

### 5. TradingView alert URL

Sau khi tunnel chạy, copy URL:
- Quick tunnel: `https://random-words.trycloudflare.com/webhooks/tradingview?token=<SMC_WEBHOOK_TOKEN>`
- Named tunnel: `https://webhook.your-domain.com/webhooks/tradingview?token=<SMC_WEBHOOK_TOKEN>`

Dán URL này vào TradingView alert "Webhook URL".

### 6. Admin access

Mở browser:
- URL: `https://admin.your-domain.com` (named) hoặc `https://random-words.trycloudflare.com` (quick)
- Cloudflare Access yêu cầu login email → bạn login → vào admin panel

## Verification

1. **Webhook reachability**:
   ```bash
   curl -X POST https://webhook.your-domain.com/webhooks/tradingview \
     -H "Content-Type: text/plain" \
     --data "SMC|v1|event=test|symbol=EURUSD|tf=M15|dir=long|level=1.1000|bar_time=1690000000|ob_id=-1|bos_id=-1|state=test|reason=ok"
   ```
   Expected: `202 Accepted` và SQLite row created.

2. **Admin access**:
   - Mở `https://admin.your-domain.com` từ browser khác (không phải máy chạy tunnel)
   - Login Cloudflare Access (email OTP)
   - Vào được Streamlit dashboard

3. **Pine alert end-to-end**:
   - Trigger Pine alert từ TradingView (manual "Test" trên alert config)
   - Verify webhook row in SQLite
   - Verify Telegram message (P0 phase 2)

## Troubleshooting

- **Quick tunnel URL đổi mỗi restart**: dùng named tunnel + domain riêng
- **Cloudflare Access không cho vào**: check email allowlist + 2FA setup
- **Webhook timeout**: TradingView timeout 3s; đảm bảo FastAPI return 202 immediately (background dispatch)
- **Local Mac sleep**: tunnel dies khi Mac sleep; chạy `caffeinate -i` để giữ awake, hoặc setup launchd service

## Costs

- Cloudflare Tunnel: **free**
- Cloudflare Access: **free** (50 users limit)
- TradingView webhook: bao gồm trong Premium subscription
- Domain (nếu dùng named tunnel): $10-15/năm nếu chưa có

**Tổng chi phí thêm: $0-15/năm**.