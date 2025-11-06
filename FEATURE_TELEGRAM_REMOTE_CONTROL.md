# Telegram Remote Control - Feature Documentation

## 📋 Overview

This document describes the **Telegram Remote Control** feature (Phase 4) that allows users to remotely monitor and control the trading strategy via Telegram commands.

**Status**: ✅ **Core Implementation Complete**

**Date**: 2025-11-06

---

## 🎯 Features Implemented

### 1. Command Response Formatters ✅

Located in `utils/telegram_bot.py`, the following command formatters have been added:

| Method | Description |
|--------|-------------|
| `format_status_response()` | Formats strategy status including equity, P&L, uptime |
| `format_position_response()` | Formats current position details with SL/TP |
| `format_pause_response()` | Formats response for pause command |
| `format_resume_response()` | Formats response for resume command |
| `format_help_response()` | Lists all available commands |

### 2. Strategy Control Methods ✅

Located in `strategy/deepseek_strategy.py`, the following control methods have been added:

| Method | Description |
|--------|-------------|
| `handle_telegram_command()` | Main command router |
| `_cmd_status()` | Retrieves and formats current strategy status |
| `_cmd_position()` | Retrieves and formats current position info |
| `_cmd_pause()` | Pauses trading (no new orders) |
| `_cmd_resume()` | Resumes trading |

### 3. Trading Pause/Resume ✅

- Added `is_trading_paused` state flag
- Integrated pause check in `_execute_trade()` method
- When paused, strategy continues monitoring but won't execute new trades
- Existing positions and SL/TP orders remain active

### 4. Uptime Tracking ✅

- Added `strategy_start_time` tracking
- Calculates and displays uptime in status responses

---

## 📱 Available Commands

### Query Commands

#### `/status` - View Strategy Status
Returns:
- Running/Paused status
- Current instrument and price
- Equity and unrealized P&L
- Last AI signal
- Uptime

**Example Response:**
```
🟢 Strategy Status

Status: RUNNING
Instrument: BTCUSDT-PERP.BINANCE
Current Price: $70,000.50
Equity: $400.00
Unrealized P&L: 📈 $15.25

Last Signal: HOLD (MEDIUM)
Signal Time: N/A
Uptime: 2h 15m
```

#### `/position` - View Current Position
Returns:
- Position side (LONG/SHORT) or no position
- Entry price and current price
- Quantity
- Unrealized P&L (amount and percentage)
- Stop Loss and Take Profit levels (if available)

**Example Response:**
```
🟢 Open Position

Side: LONG
Quantity: 0.0010
Entry Price: $69,500.00
Current Price: $70,000.50

Unrealized P&L: 📈 $0.50 (+0.72%)

🛡️ Stop Loss: $68,500.00
🎯 Take Profit: $71,500.00
```

#### `/help` - Show Available Commands
Lists all commands with descriptions

### Control Commands

#### `/pause` - Pause Trading
- Stops executing new trade signals
- Keeps strategy running and monitoring
- Existing positions remain open
- SL/TP orders remain active

**Response:**
```
⏸️ Strategy Paused

Trading has been paused. No new orders will be placed.
Use /resume to continue trading.
```

#### `/resume` - Resume Trading
- Re-enables trade execution
- Strategy resumes normal operation

**Response:**
```
▶️ Strategy Resumed

Trading has been resumed. Strategy is now active.
```

---

## 🧪 Testing

### Manual Testing

Use the provided test script to verify command formatters:

```bash
# Test status command
python test_telegram_commands.py status

# Test position command
python test_telegram_commands.py position

# Test pause command
python test_telegram_commands.py pause

# Test resume command
python test_telegram_commands.py resume

# Test help command
python test_telegram_commands.py help
```

Each test will:
1. Display the formatted message
2. Ask if you want to send it to Telegram
3. Send the message if confirmed

---

## 📐 Architecture

### Current Implementation

```
┌─────────────────────────────────────────────────────┐
│ Telegram App (User)                                  │
└──────────────────┬──────────────────────────────────┘
                   │ (Manual Testing Only)
                   │
┌──────────────────┴──────────────────────────────────┐
│ TelegramBot (utils/telegram_bot.py)                 │
│  • format_status_response()                         │
│  • format_position_response()                       │
│  • format_pause_response()                          │
│  • format_resume_response()                         │
│  • format_help_response()                           │
└──────────────────┬──────────────────────────────────┘
                   │
┌──────────────────┴──────────────────────────────────┐
│ DeepSeekAIStrategy (strategy/deepseek_strategy.py)  │
│  • handle_telegram_command() - Command router       │
│  • _cmd_status() - Status query                     │
│  • _cmd_position() - Position query                 │
│  • _cmd_pause() - Pause trading                     │
│  • _cmd_resume() - Resume trading                   │
│  • is_trading_paused - State flag                   │
└─────────────────────────────────────────────────────┘
```

### Future Enhancement: Automatic Command Listening

The `TelegramCommandHandler` class (`utils/telegram_command_handler.py`) is ready for future integration but requires:
- Threading or async event loop integration
- Proper lifecycle management within NautilusTrader framework
- Testing in production environment

**Planned Architecture:**
```
Telegram Bot API
       ↓
TelegramCommandHandler (polling in background thread)
       ↓
Strategy.handle_telegram_command()
       ↓
Execute command & return response
       ↓
Send response via TelegramBot
```

---

## 🔒 Security Considerations

### Current Status (Manual Testing)
- Commands can only be tested manually via script
- No security concerns as no automatic listening is active

### Future Implementation Security
1. **Chat ID Whitelist**: Only authorized chat IDs can send commands
2. **Command Authentication**: Each command checks authorization
3. **Rate Limiting**: Prevents command spam
4. **Secure Token Storage**: Bot token stored in `.env` file (not committed)
5. **Read-Only Commands**: Query commands (`/status`, `/position`) are safe
6. **Control Commands**: Pause/resume affect trading but don't close positions

### Security Checklist for Production
- [ ] Verify bot token is kept secret
- [ ] Add only trusted chat IDs to whitelist
- [ ] Monitor command logs for suspicious activity
- [ ] Consider adding confirmation for control commands
- [ ] Implement rate limiting on commands
- [ ] Set up alerts for unauthorized access attempts

---

## 📝 Configuration

### Enable/Disable Remote Control

In `configs/strategy_config.yaml`:

```yaml
telegram:
  enabled: true  # Must be true
  bot_token: ""  # Read from .env
  chat_id: ""    # Read from .env
  notify_signals: true
  notify_fills: true
  notify_positions: true
  notify_errors: true
```

### Environment Variables

In `.env` file:

```bash
# Telegram Configuration
TELEGRAM_BOT_TOKEN="your_bot_token_here"
TELEGRAM_CHAT_ID="your_chat_id_here"
```

---

## 🐛 Known Limitations

1. **No Automatic Command Listening**
   - Current implementation requires manual testing
   - Automatic command polling not integrated with NautilusTrader lifecycle
   - Future version will include background thread for automatic listening

2. **Single Chat ID Support**
   - Currently supports one chat ID
   - Future: Multiple authorized users

3. **No Command History**
   - Commands are not logged/stored
   - Future: Add command audit log

4. **Limited Position Info**
   - SL/TP prices not tracked in position response
   - Requires separate tracking mechanism

---

## 🚀 Usage Example

Once automatic listening is implemented:

```
User: /status
Bot: 🟢 Strategy Status
     Status: RUNNING
     ...

User: /position
Bot: 🟢 Open Position
     Side: LONG
     ...

User: /pause
Bot: ⏸️ Strategy Paused
     ...

User: /resume
Bot: ▶️ Strategy Resumed
     ...
```

---

## 📊 Implementation Summary

| Component | Status | Location |
|-----------|--------|----------|
| Command Formatters | ✅ Complete | `utils/telegram_bot.py` |
| Strategy Control Methods | ✅ Complete | `strategy/deepseek_strategy.py` |
| Pause/Resume Logic | ✅ Complete | `strategy/deepseek_strategy.py` |
| Uptime Tracking | ✅ Complete | `strategy/deepseek_strategy.py` |
| Manual Test Script | ✅ Complete | `test_telegram_commands.py` |
| Command Handler (Auto) | ⏳ Ready (Not Integrated) | `utils/telegram_command_handler.py` |

---

## 🔮 Future Enhancements

### Phase 4.1: Automatic Command Listening
- Integrate `TelegramCommandHandler` with strategy lifecycle
- Run command polling in background thread
- Handle async communication properly

### Phase 4.2: Advanced Commands
- `/close` - Close current position
- `/orders` - View open orders
- `/history` - View recent trades
- `/risk` - View risk metrics

### Phase 4.3: Interactive Features
- Confirmation buttons for control commands
- Inline keyboards for command selection
- Real-time price alerts

### Phase 4.4: Multi-User Support
- Multiple authorized users
- Different permission levels
- User-specific settings

---

## 📚 Related Files

- `utils/telegram_bot.py` - Bot class with formatters
- `utils/telegram_command_handler.py` - Command polling handler (future use)
- `strategy/deepseek_strategy.py` - Strategy with control methods
- `test_telegram_commands.py` - Manual testing script
- `configs/strategy_config.yaml` - Configuration
- `.env` - Telegram credentials

---

## ✅ Testing Checklist

- [x] Command formatters return valid markdown
- [x] Status command retrieves correct data
- [x] Position command handles no position case
- [x] Pause command sets flag correctly
- [x] Resume command clears flag correctly
- [x] Help command lists all commands
- [ ] Automatic command listening (future)
- [ ] Multi-user authorization (future)
- [ ] Rate limiting (future)

---

**Implementation Date**: 2025-11-06  
**Version**: 1.0 (Core Implementation)  
**Next Steps**: Test with live strategy, then integrate automatic listening

