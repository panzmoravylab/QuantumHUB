# Quantum HUD — Tier 5 roadmap (navazující implementace)

## 1. TradingView zóny

- Soubor: `integrations/tradingview_zones.py`
- Env: `TRADINGVIEW_ZONES_PATH=path/to/zones.json`
- Další krok: overlay horizontálních linek a obdélníků v `layouts/quadrant_d.py`

## 2. Telegram notifikace

- Soubor: `integrations/notifications.py`
- Env: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- Další krok: volat `notify()` z `alerts.py` při CRITICAL/BLOK

## 3. Order entry

- Soubor: `integrations/order_entry.py`
- Env: `ORDER_ENTRY_ENABLED=true` (default false)
- Další krok: tlačítko v hero panelu + MT5 `order_send` s potvrzením

## 4. Rizika

- Order entry vyžaduje dvojité potvrzení a demo test
- Telegram token nesmí do gitu
- TV zóny musí být validované proti aktuální ceně
