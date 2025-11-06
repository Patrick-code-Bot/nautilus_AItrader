# 📱 Telegram Setup Guide

## Quick Start

### Step 1: Create Telegram Bot

1. Open Telegram and search for `@BotFather`
2. Send `/newbot` command
3. Follow the instructions:
   - Choose a name for your bot
   - Choose a username (must end with 'bot')
4. Copy the **Bot Token** (looks like: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

### Step 2: Get Your Chat ID

**Method 1: Using @userinfobot (Easiest)**
1. Search for `@userinfobot` in Telegram
2. Send any message to it
3. It will reply with your user ID (a number like `987654321`)

**Method 2: Using API**
1. Send a message to your bot (send `/start`)
2. Visit this URL in your browser (replace `<YOUR_BOT_TOKEN>`):
   ```
   https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates
   ```
3. Look for `"chat":{"id":123456789}` in the response

### Step 3: Configure Your Bot

Add these lines to your `.env` file:

```bash
# Telegram Notifications
TELEGRAM_BOT_TOKEN="YOUR_BOT_TOKEN_HERE"  # From @BotFather
TELEGRAM_CHAT_ID="YOUR_CHAT_ID_HERE"      # Your Telegram user ID
TELEGRAM_ENABLED=true                      # Enable notifications
```

**Example:**
```bash
TELEGRAM_BOT_TOKEN="123456789:ABCdefGHIjklMNOpqrsTUVwxyz"
TELEGRAM_CHAT_ID="987654321"
TELEGRAM_ENABLED=true
```

### Step 4: Test Your Connection

Run the test script:

```bash
cd /home/ubuntu/nautilus_deepseek
source /home/ubuntu/deepseek_venv/bin/activate
python test_telegram.py
```

Or test with explicit credentials:

```bash
python test_telegram.py "YOUR_BOT_TOKEN" "YOUR_CHAT_ID"
```

If successful, you should receive a test message on Telegram!

### Step 5: Enable in Configuration

Edit `configs/telegram_config.yaml`:

```yaml
telegram:
  enabled: true  # Change from false to true
  # ... rest of config
```

### Step 6: Restart Strategy

```bash
./restart_trader.sh
```

You should receive a "Strategy Started" message on Telegram!

---

## Notification Types

Your bot will send these notifications:

### 📊 Trading Signals
```
🟢 Trading Signal Detected
Signal: BUY
Confidence: HIGH
Price: $50,000.00
...
```

### ✅ Order Fills
```
🟢 Order Filled
Side: BUY
Type: MARKET
Quantity: 0.001 BTC
Price: $50,000.00
```

### 📈 Position Updates
```
📈 Position Opened
Side: LONG
Quantity: 0.001 BTC
Entry Price: $50,000.00
```

### 🎯 Partial Take Profit
```
🎯 Partial Take Profit - Level 1
Closed: 0.0005 BTC
Price: $51,000.00
Profit: +2.0%
```

### 🔄 Trailing Stop Updates
```
🔄 Trailing Stop Updated
Current Price: $51,500.00
Profit: +3.0%
Stop Loss: $50,500.00 ⬆️
```

### ❌ Errors & Warnings
```
⚠️ WARNING
Failed to submit order: Insufficient margin
```

---

## Troubleshooting

### "❌ Failed to connect to Telegram"

**Check:**
- Bot token is correct (no extra spaces)
- Internet connection is working
- Telegram is not blocked by firewall

### "❌ Unauthorized" or "403 Forbidden"

**Solution:**
- Make sure you sent `/start` to your bot first
- Check that chat ID is correct

### "Test passed but no message received"

**Check:**
- Chat ID is correct (use @userinfobot to verify)
- You're checking the correct Telegram account
- Bot is not blocked by you

### "ImportError: python-telegram-bot not found"

**Solution:**
```bash
source /home/ubuntu/deepseek_venv/bin/activate
pip install python-telegram-bot
```

---

## Security Best Practices

### ✅ DO:
- Keep your bot token secret
- Never commit `.env` file to Git
- Use a dedicated bot for each project
- Regularly rotate tokens if compromised

### ❌ DON'T:
- Share your bot token publicly
- Commit tokens to GitHub
- Use the same bot for multiple sensitive projects
- Store tokens in plain text files outside `.env`

---

## Advanced Configuration

### Quiet Hours

Don't want notifications at night? Edit `configs/telegram_config.yaml`:

```yaml
quiet_hours:
  enabled: true
  start: "00:00"  # UTC time
  end: "08:00"    # UTC time
  urgent_only: true  # Only critical alerts during quiet hours
```

### Rate Limiting

Prevent spam:

```yaml
rate_limit:
  enabled: true
  max_messages_per_minute: 10
  burst_size: 5
```

### Selective Notifications

Choose what to receive:

```yaml
notifications:
  trade_signals: true
  order_fills: true
  position_updates: true
  partial_tp: true
  trailing_stop: true
  errors: true
  warnings: false  # Disable warnings
```

---

## Testing Checklist

- [ ] Created bot with @BotFather
- [ ] Got bot token
- [ ] Got chat ID
- [ ] Added credentials to `.env`
- [ ] Ran `test_telegram.py` successfully
- [ ] Received test message on Telegram
- [ ] Enabled in `telegram_config.yaml`
- [ ] Restarted strategy
- [ ] Received strategy startup message

---

## Quick Reference

| Action | Command |
|--------|---------|
| Test connection | `python test_telegram.py` |
| Check bot status | `grep "Telegram" logs/trader.log` |
| Disable notifications | Set `TELEGRAM_ENABLED=false` in `.env` |
| View config | `cat configs/telegram_config.yaml` |

---

**Need Help?**

Check the logs:
```bash
tail -100 logs/trader.log | grep -i telegram
```

---

**Last Updated**: 2025-11-06  
**Version**: 1.0.0  
**Status**: Ready for Production

