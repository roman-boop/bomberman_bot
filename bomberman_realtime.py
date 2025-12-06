# Real-time Bomberman Bot for BingX Futures
# Based on the provided strategy
# WARNING: This is for educational purposes. Use at your own risk!
# Add your API keys and test first.

import pandas as pd
import numpy as np
import time
from datetime import datetime
from bingx_client import BingxClient  # Импорт клиента (предполагая файл bingx_client_new.py в той же директории)

# --- НАСТРОЙКИ ---
SYMBOL = 'BTCUSDT'             # Без дефиса, клиент добавит -USDT
LEVERAGE = 20                  # Плечо (если нужно установить, добавить функцию)
RISK_PER_TRADE = 0.01          # Риск на сделку (1%)
INITIAL_CAPITAL = 1000.0       # Начальный капитал (USDT) - для расчёта size, если balance не доступен
TOL = 0.01                   # Tolerance из best params (замени на свои)
DIRECTION = 'both'             # 'long', 'short', 'both'
MR_PERIOD = 45                 # Из grid_search best
MR_MULT = 2.5
DC_PERIOD = 14
BOP_SMOOTH = 2

# API ключи (ЗАМЕНИ НА СВОИ!)
API_KEY = ''
API_SECRET = ''

bx = BingxClient(API_KEY, API_SECRET, SYMBOL)

# --- Функция загрузки свечей для BingX (адаптировано) ---
def fetch_latest_klines(interval, limit=100):
    path = "/openApi/swap/v2/quote/klines"
    params = {
        "symbol": bx.symbol,
        "interval": interval,
        "limit": str(limit)
    }
    try:
        data = bx._public_request(path, params)
        if data.get('code') == 0 and 'data' in data:
            klines = data['data']
            df = pd.DataFrame(klines, columns=['time', 'open', 'high', 'low', 'close', 'volume'])
            df['time'] = pd.to_datetime(df['time'], unit='ms')
            df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
            return df
        return pd.DataFrame()
    except Exception as e:
        print(f"Ошибка fetch: {e}")
        return pd.DataFrame()

# Индикаторы (как в оригинале)
def add_bop(df: pd.DataFrame, smooth: int = 1) -> pd.DataFrame:
    df = df.copy()
    df['bop'] = (df['close'] - df['open']) / (df['high'] - df['low']).replace(0, np.nan)
    if smooth > 1:
        df['bop'] = df['bop'].rolling(smooth).mean()
    return df

def add_mean_reversion(df: pd.DataFrame, period: int = 20, mult: float = 2.0) -> pd.DataFrame:
    df = df.copy()
    df['sma'] = df['close'].rolling(period).mean()
    df['std'] = df['close'].rolling(period).std()
    df['upper'] = df['sma'] + mult * df['std']
    df['lower'] = df['sma'] - mult * df['std']
    return df

def add_donchian(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    df = df.copy()
    df['donchian_high'] = df['high'].rolling(period).max()
    df['donchian_low']  = df['low'].rolling(period).min()
    return df

# Синхронизация (как в оригинале)
def sync_timeframes(df30, df15, df5):
    df30 = df30.set_index('time')
    df15 = df15.set_index('time')
    df5 = df5.set_index('time')
    df = df30.join(df15[['upper', 'lower']], how='left')
    df = df.join(df5[['donchian_high', 'donchian_low']], how='left')
    cols = ['upper', 'lower', 'donchian_high', 'donchian_low']
    df[cols] = df[cols].ffill()
    df = df.reset_index()
    return df

# --- Функции торговли (адаптировано для BingX) ---
def get_current_price():
    return bx.get_mark_price(symbol='BTC-USDT')

def get_balance():
    try:
        path = "/openApi/swap/v2/user/balance"
        data = bx._request("GET", path)
        if data.get('code') == 0 and 'data' in data:
            return float(data['data'][0]['balance'])  # Предполагая USDT баланс
        return INITIAL_CAPITAL
    except Exception as e:
        print(f"Ошибка balance: {e}")
        return INITIAL_CAPITAL

def open_position(side, size):
    try:
        price = bx.get_mark_price('BTC-USDT')
        stop = 0.99 * price if side == 'long' else 1.01 * price
        stop = round(stop,1)
        resp = bx.place_market_order(side, size, 'BTC-USDT', stop = stop)
        if resp.get('code') == 0:
            print(f"Открыта позиция: {side} size {size}")
            mark_price = get_current_price()
            return resp
        else:
            print(f"Ошибка open: {resp.get('msg')}")
            return None
    except Exception as e:
        print(f"Ошибка open: {e}")
        return None

def close_position(side, size):
    # Для закрытия - противоположный side
    close_side = 'long' if side == 'short' else 'short'  # Противоположный для закрытия
    try:
        params = {
            "symbol": bx.symbol,
            "side": "SELL" if close_side == "short" else "BUY",
            "positionSide": "SHORT" if close_side == "short" else "LONG",
            "type": "MARKET",
            "timestamp": int(time.time() * 1000),
            "quantity": size,
            "recvWindow": 5000,
            "reduceOnly": "true"  # ← Добавляем reduceOnly для закрытия
        }
        resp = bx._request("POST", "/openApi/swap/v2/trade/order", params)
        if resp.get('code') == 0:
            print(f"Закрыта позиция: size {size}")
            return resp
        else:
            print(f"Ошибка close: {resp.get('msg')}")
            return None
    except Exception as e:
        print(f"Ошибка close: {e}")
        return None

def get_position():
    try:
        positions = bx.get_positions()
        if positions:
            pos = positions[0]
            qty = float(pos.get('positionAmt', 0))
            entry = float(pos.get('avgPrice', 0))
            if qty > 0:
                return 1, entry  # long
            elif qty < 0:
                return -1, entry  # short
        return 0, 0.0
    except Exception as e:
        print(f"Ошибка position: {e}")
        return 0, 0.0

import time
from datetime import datetime
INTERVAL_MINUTES = 5

last_check = None

if __name__ == "__main__":
    print("Bot started...")

    # Initial load (last 100 candles for warmup)
    df_30m = fetch_latest_klines('30m', 100)
    df_15m = fetch_latest_klines('15m', 200)
    df_5m = fetch_latest_klines('5m', 600)

    while True:
        
        now = datetime.now()
        current_minute = now.minute
        current_second = now.second

        # Проверяем, что минута делится на 5 и секунда < 10 (чтобы не срабатывать много раз)
        if (current_minute % INTERVAL_MINUTES == 5) and current_second < 10:
            if last_check != current_minute:  # Чтобы не сработало 10 раз за первые 10 сек
                # Update DFs
                new_30m = fetch_latest_klines('30m', 5)
                df_30m = pd.concat([df_30m, new_30m]).drop_duplicates('time').sort_values('time').tail(100)

                new_15m = fetch_latest_klines('15m', 10)
                df_15m = pd.concat([df_15m, new_15m]).drop_duplicates('time').sort_values('time').tail(200)

                new_5m = fetch_latest_klines('5m', 30)
                df_5m = pd.concat([df_5m, new_5m]).drop_duplicates('time').sort_values('time').tail(600)

                # Calculate
                df_bop = add_bop(df_30m, BOP_SMOOTH)
                df_mr = add_mean_reversion(df_15m, MR_PERIOD, MR_MULT)
                df_dc = add_donchian(df_5m, DC_PERIOD)
                
                # Sync
                df_sync = sync_timeframes(df_bop, df_mr, df_dc)
                print(len(df_sync))
                if len(df_sync) < 50:
                    continue

                row = df_sync.iloc[-1]
                prev = df_sync.iloc[-2]

                price = get_current_price()
                print(price)
                if price is None:
                    continue

                capital = get_balance()

                # Get current position
                position, entry_price = get_position()
                
                # ВХОД
                if position == 0:
                    if DIRECTION in ['long', 'both']:
                        long_cond = (
                            row['bop'] > 0 and
                            price <= row['lower'] * (1 + TOL) and
                            price > prev['donchian_high']
                        )
                        if long_cond:
                            size = (capital * RISK_PER_TRADE * LEVERAGE) / price
                            # Округлить size по правилам биржи (добавить precision если нужно)
                            open_position('long', size)
                            print(f"LONG opened at {price}")

                    if DIRECTION in ['short', 'both']:
                        short_cond = (
                            row['bop'] < 0 and
                            price >= row['upper'] * (1 - TOL) and
                            price < prev['donchian_low']
                        )
                        if short_cond:
                            size = (capital * RISK_PER_TRADE * LEVERAGE) / price
                            open_position('short', size)
                            print(f"SHORT opened at {price}")
                print(position, len(df_30m), short_cond, long_cond)
                # ВЫХОД (проверяем условия)
                if position == 1:  # LONG
                    if price >= row['upper'] or price <= entry_price * 0.99:
                        pos_size = abs(get_position()[1])  # Получить текущий size
                        close_position('long', pos_size)  # Закрыть long
                        print(f"{'EXIT' if price >= row['upper'] else 'STOP'} LONG at {price}")

                if position == -1:  # SHORT
                    if price <= row['lower'] or price >= entry_price * 1.01:
                        pos_size = abs(get_position()[1])
                        close_position('short', pos_size)  # Закрыть short
                        print(f"{'EXIT' if price <= row['lower'] else 'STOP'} SHORT at {price}")
                
                last_check = now.minute

                time.sleep(5)
