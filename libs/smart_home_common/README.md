# Smart Home Common Library

Shared Python utilities for all Smart Home services.

## Modules

- **mqtt/** - MQTT handler and subscription manager
- **persistence/** - State persistence utilities  
- **clients/** - External service clients (MELCloud, Zigbee2MQTT)
- **telegram** - Unified synchronous Telegram notification client
- **utils/** - Common utilities (error tracking, etc.)

## Installation

From any service directory:

```bash
pip install -e ../../libs/smart_home_common
```

Or in Dockerfile:

```dockerfile
COPY libs/smart_home_common /tmp/smart_home_common
RUN pip install /tmp/smart_home_common
```

## Usage

```python
from smart_home_common.mqtt import MQTTHandler
from smart_home_common.persistence import StatePersistence
from smart_home_common.clients import MELCloudClient
```

## Telegram notifications

A unified synchronous Telegram client (built on `httpx`) is shared by all
services, so each one sends alerts the same way without pulling in asyncio or
`python-telegram-bot`.

```python
from smart_home_common.telegram import TelegramNotifier

# Explicit configuration
notifier = TelegramNotifier(
    bot_token="123456:ABC-DEF",
    chat_ids=["111111111", "222222222"],
)

# Or load from environment variables:
#   TELEGRAM_BOT_TOKEN  bot token from @BotFather (required)
#   TELEGRAM_CHAT_IDS   comma-separated chat IDs (preferred)
#   TELEGRAM_CHAT_ID    single chat ID (fallback, backwards compat)
notifier = TelegramNotifier.from_env()

if notifier.enabled:
    notifier.send("Plain text alert")          # no parse mode
    notifier.send_markdown("*Bold* alert")      # Markdown parse mode

    result = notifier.send("Another alert")
    if result.success:
        print(f"Delivered to {result.successful_count} chat(s)")
    else:
        print(result.message)  # describes partial/total failure
```

`send()` and `send_markdown()` return a `TelegramResult` dataclass with
`success`, `message`, `successful_count` and `failed_count`. Delivery is
attempted for every configured chat; `success` is `True` only when every chat
received the message.
