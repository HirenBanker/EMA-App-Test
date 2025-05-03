
import sys
import os
import threading
import time
import json
from datetime import datetime, timedelta

import yfinance as yf
import pandas as pd
import numpy as np
import tkinter as tk
from tkinter import ttk, messagebox
import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt

# If frozen (packaged as exe), set working directory to the executable's directory.
if getattr(sys, 'frozen', False):
    application_path = os.path.dirname(sys.executable)
    os.chdir(application_path)
    print(f"Running in frozen mode. Working directory set to: {application_path}")

# If on Windows, minimize the console window so that it does not distract the user.
if sys.platform.startswith("win"):
    import ctypes
    SW_MINIMIZE = 6
    hWnd = ctypes.windll.kernel32.GetConsoleWindow()
    if hWnd:
        ctypes.windll.user32.ShowWindow(hWnd, SW_MINIMIZE)

# Global variables for status updates, open position info, simulation status,
# forced square-off, persistent open position, and the simulation message.
latest_status = {}
position_status = {}
simulation_status = "No signal yet."
force_square_off = False
open_position_data = None  # Will hold open position details persistently.
simulation_message = "No daily info yet."  # Displayed on the third line.
# Global variable to store user-selected interval
selected_interval = "1h"  # Default value

def update_interval():
    """Update selected interval from GUI."""
    global selected_interval
    selected_interval = interval_combobox.get()
    status_label.config(text=f"Interval updated to: {selected_interval}", fg="blue")


# --------------------------
# Persistence Functions
# --------------------------

def load_open_position():
    global open_position_data
    if os.path.exists("open_position.json"):
        try:
            with open("open_position.json", "r") as f:
                open_position_data = json.load(f)
                print("Loaded open position from file.")
        except Exception as e:
            print("Error loading open position:", e)
            open_position_data = None
    else:
        open_position_data = None

def save_open_position():
    global open_position_data
    try:
        with open("open_position.json", "w") as f:
            json.dump(open_position_data, f)
            print("Saved open position to file.")
    except Exception as e:
        print("Error saving open position:", e)

def load_simulation_params():
    if os.path.exists("simulation_params.json"):
        try:
            with open("simulation_params.json", "r") as f:
                params = json.load(f)
                print("Loaded simulation parameters from file.")
                return params
        except Exception as e:
            print("Error loading simulation parameters:", e)
            return None
    else:
        return None

def save_simulation_params(params):
    try:
        with open("simulation_params.json", "w") as f:
            json.dump(params, f)
            print("Saved simulation parameters to file.")
    except Exception as e:
        print("Error saving simulation parameters:", e)

# --------------------------
# Open Position Display Update Function
# --------------------------

def update_open_position_display():
    if open_position_data is not None:
        pos_signal_val.config(text="BUY")
        try:
            entry_price = float(open_position_data.get("entry_price", 0))
            pos_price_val.config(text=f"{entry_price:.2f}")
        except Exception:
            pos_price_val.config(text="N/A")
        try:
            shares = float(open_position_data.get("shares", 0))
            pos_qty_val.config(text=f"{shares:.2f}")
        except Exception:
            pos_qty_val.config(text="N/A")
        try:
            # Use the latest market price if available; otherwise fallback to entry price.
            if "price" in latest_status:
                current_price = float(latest_status["price"])
            else:
                current_price = entry_price
            current_value = current_price * shares
            pos_value_val.config(text=f"{current_value:.2f}")
        except Exception:
            pos_value_val.config(text="N/A")
        try:
            if "price" in latest_status:
                current_price = float(latest_status["price"])
            else:
                current_price = entry_price
            pl = (current_price - entry_price) * shares
            pos_pl_val.config(text=f"{pl:.2f}")
        except Exception:
            pos_pl_val.config(text="N/A")
    else:
        pos_signal_val.config(text="N/A")
        pos_price_val.config(text="N/A")
        pos_qty_val.config(text="N/A")
        pos_value_val.config(text="N/A")
        pos_pl_val.config(text="N/A")

# --------------------------
# Initial Setup Function
# --------------------------

def initial_setup():
    global selected_interval
    load_open_position()
    sim_params = load_simulation_params()
    if sim_params:
        ticker_entry.delete(0, tk.END)
        ticker_entry.insert(0, sim_params.get("ticker", ""))
        ema_short_entry.delete(0, tk.END)
        ema_short_entry.insert(0, str(sim_params.get("ema_short_period", "5")))
        ema_long_entry.delete(0, tk.END)
        ema_long_entry.insert(0, str(sim_params.get("ema_long_period", "13")))
        stoploss_entry.delete(0, tk.END)
        stoploss_entry.insert(0, str(sim_params.get("stoploss", "5")))
        target_entry.delete(0, tk.END)
        target_entry.insert(0, str(sim_params.get("target", "10")))
        # Load saved interval if available
        saved_interval = sim_params.get("interval")
        if saved_interval and saved_interval in ["1wk", "1d", "1h", "15m"]:
            selected_interval = saved_interval
            interval_combobox.set(selected_interval)
    if open_position_data is not None:
        ticker_entry.config(state='disabled')
        ema_short_entry.config(state='disabled')
        ema_long_entry.config(state='disabled')
        stoploss_entry.config(state='disabled')
        target_entry.config(state='disabled')
        print("Overnight open position detected; input boxes are disabled.")
        update_open_position_display()

# --------------------------
# Indicator Calculation Functions
# --------------------------

def heikin_ashi(df):
    """
    Convert standard OHLC candles into Heikin Ashi candles.
    Returns a new DataFrame with columns: HA_Open, HA_High, HA_Low, HA_Close.
    """
    df = df.copy()
    df[['Open','High','Low','Close']] = df[['Open','High','Low','Close']].apply(pd.to_numeric, errors='coerce')
    ha = pd.DataFrame(index=df.index, columns=['HA_Open', 'HA_High', 'HA_Low', 'HA_Close'])
    ha['HA_Close'] = ((df['Open'] + df['High'] + df['Low'] + df['Close']) / 4).astype(float)
    ha.iloc[0, ha.columns.get_loc('HA_Open')] = (df['Open'].values.item(0) + df['Close'].values.item(0)) / 2
    for i in range(1, len(df)):
        ha.iloc[i, ha.columns.get_loc('HA_Open')] = (ha['HA_Open'].iloc[i-1] + ha['HA_Close'].iloc[i-1]) / 2
    ha['HA_High'] = pd.concat([
        df['High'].astype(float),
        ha['HA_Open'].astype(float),
        ha['HA_Close'].astype(float)
    ], axis=1).max(axis=1)
    ha['HA_Low'] = pd.concat([
        df['Low'].astype(float),
        ha['HA_Open'].astype(float),
        ha['HA_Close'].astype(float)
    ], axis=1).min(axis=1)
    return ha

def calculate_tsi(series, r=25, s=13, signal_period=13):
    """
    Calculate the True Strength Index (TSI) and its signal line.
    """
    diff = series.diff()
    abs_diff = diff.abs()
    ema1 = diff.ewm(span=r, adjust=False).mean()
    ema2 = ema1.ewm(span=s, adjust=False).mean()
    abs_ema1 = abs_diff.ewm(span=r, adjust=False).mean()
    abs_ema2 = abs_ema1.ewm(span=s, adjust=False).mean()
    tsi = 100 * (ema2 / abs_ema2)
    tsi_signal = tsi.ewm(span=signal_period, adjust=False).mean()
    return tsi, tsi_signal

# --------------------------
# Live Data Update Function using Heikin Ashi
# --------------------------

def update_live_data(ticker, ema_short_period, ema_long_period, interval='1h'):
    """
    Download recent data, convert to Heikin Ashi candles,
    and calculate EMA and TSI on HA_Close.
    """
    global selected_interval
    # Use the global selected_interval instead of the parameter
    data = yf.download(ticker, period="60d", interval=selected_interval)
    if data.empty:
        print(f"No data available for {ticker} with interval {selected_interval}.")
        return None
    data.index = pd.to_datetime(data.index)
    ha = heikin_ashi(data)
    ha['EMA_short'] = ha['HA_Close'].ewm(span=ema_short_period, adjust=False).mean()
    ha['EMA_long'] = ha['HA_Close'].ewm(span=ema_long_period, adjust=False).mean()
    tsi, tsi_signal = calculate_tsi(ha['HA_Close'], r=25, s=13, signal_period=13)
    ha['TSI'] = tsi
    ha['TSI_Signal'] = tsi_signal
    return ha

# --------------------------
# Signal and Trade Recording Functions
# --------------------------

def record_signal(file, date, hour, price):
    row = pd.DataFrame({
        'Date': [date],
        'Hour': [hour],
        'Price': [round(price, 2)]
    })
    if not os.path.exists(file):
        row.to_pickle(file)
    else:
        existing_df = pd.read_pickle(file)
        combined_df = pd.concat([existing_df, row], ignore_index=True)
        combined_df.to_pickle(file)

def record_trade(trade_file, entry_date, entry_hour, entry_price, exit_date, exit_hour, exit_price, pl, account_balance):
    row = pd.DataFrame({
        'Entry Date': [entry_date],
        'Entry Hour': [entry_hour],
        'Entry Price': [round(entry_price, 2)],
        'Exit Date': [exit_date],
        'Exit Hour': [exit_hour],
        'Exit Price': [round(exit_price, 2)],
        'P/L': [round(pl, 2)],
        'Account Balance': [round(account_balance, 2)]
    })
    if not os.path.exists(trade_file):
        row.to_pickle(trade_file)
    else:
        existing_df = pd.read_pickle(trade_file)
        combined_df = pd.concat([existing_df, row], ignore_index=True)
        combined_df.to_pickle(trade_file)

# --------------------------
# Live Trading Loop using EMA/TSI Heikin Ashi Strategy
# --------------------------

def live_trading(ticker, ema_short_period, ema_long_period, initial_capital, stop_event, open_pos=None, stoploss=5.0, target=10.0, interval='1h'):
    global latest_status, position_status, simulation_status, force_square_off, open_position_data, simulation_message, selected_interval
    entry_file = "entry_signals.pkl"
    exit_file = "exit_signals.pkl"
    trade_file = "trade_data.pkl"
    
    if open_pos is not None:
        in_position = True
        entry_price = open_pos.get("entry_price")
        entry_date = open_pos.get("entry_date")
        entry_hour = open_pos.get("entry_hour")
        shares = open_pos.get("shares")
        account_balance = open_pos.get("account_balance")
    else:
        in_position = False
        entry_price = None
        entry_date = None
        entry_hour = None
        shares = 0.0
        account_balance = initial_capital

    simulation_status = "Simulation started."
    print("Starting live EMA/TSI paper trading simulation...")

    while not stop_event.is_set():
        if stop_event.is_set():
            break

        print(f"\n--- Data Update at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---")
        ha_data = update_live_data(ticker, ema_short_period, ema_long_period, interval)
        if ha_data is None or len(ha_data) < 2:
            simulation_status = "Data update failed; skipping iteration."
            simulation_message = simulation_status
            print(simulation_status)
            total_wait = 60
            interval_wait = 0.5
            waited = 0
            while waited < total_wait:
                if stop_event.is_set() or force_square_off:
                    break
                time.sleep(interval_wait)
                waited += interval_wait
            if stop_event.is_set():
                break
            continue

        prev_candle = ha_data.iloc[-2]
        current_candle = ha_data.iloc[-1]
        current_date = current_candle.name.strftime("%d-%b-%Y")
        current_hour = datetime.now().strftime("%H:%M")
        current_price = float(current_candle['HA_Close'])

        latest_status = {
            "date": current_date,
            "hour": current_hour,
            "price": current_price
        }

        print(f"Latest HA Candle -> Date: {current_date}, Price: {current_price:.2f}, EMA_short: {current_candle['EMA_short']:.2f}, EMA_long: {current_candle['EMA_long']:.2f}")

        if current_candle['TSI'] > 0:
            simulation_message = "Entry condition satisfied"
        elif current_candle['TSI'] < 0:
            simulation_message = "Entry condition not satisfied"

        if not in_position:
            if (current_candle['TSI'] > 0) and ((current_candle['TSI'] - current_candle['TSI_Signal']) > 0) and (current_candle['EMA_short'] > current_candle['EMA_long']):
                simulation_status = "Entry signal detected: Entering position..."
                print(simulation_status)
                root.after(0, lambda: messagebox.showinfo("Entry Signal", "Entry signal detected: Entering position."))
                record_signal(entry_file, current_date, current_hour, current_price)
                entry_price = current_price
                entry_date = current_date
                entry_hour = current_hour
                shares = account_balance / entry_price
                account_balance = 0.0
                in_position = True
                open_position_data = {
                    "entry_price": entry_price,
                    "entry_date": entry_date,
                    "entry_hour": entry_hour,
                    "shares": shares,
                    "account_balance": account_balance
                }
                root.after(0, update_open_position_display)
                print(f"Entered position at {entry_price} (Bought {shares:.4f} shares)")
            else:
                simulation_status = "No entry signal detected; waiting..."
                print(simulation_status)
        else:
            current_value = shares * current_price
            pl_open = current_value - (shares * entry_price)
            position_status = {
                "Signal": "BUY",
                "Entry Price": f"{entry_price:.2f}",
                "Shares": f"{shares:.4f}",
                "Current Value": f"{current_value:.2f}",
                "P/L": f"{pl_open:.2f}"
            }
            exit_condition = False
            if current_price < float(prev_candle['HA_Low']):
                exit_condition = True
                simulation_status = "Exit: Price fell below previous HA candle's low."
            elif current_price >= entry_price * (1 + target/100):
                exit_condition = True
                simulation_status = "Exit: Target reached."
            elif current_price <= entry_price * (1 - stoploss/100):
                exit_condition = True
                simulation_status = "Exit: Stoploss reached."
            elif force_square_off:
                exit_condition = True
                simulation_status = "Square-off triggered: Exiting position."
            
            if exit_condition:
                root.after(0, lambda: messagebox.showinfo("Exit Signal", simulation_status))
                record_signal(exit_file, current_date, current_hour, current_price)
                exit_price = current_price
                trade_value = shares * exit_price
                pl = trade_value - (shares * entry_price)
                account_balance = trade_value
                in_position = False
                record_trade(trade_file, entry_date, entry_hour, entry_price, current_date, current_hour, exit_price, pl, account_balance)
                print(f"Exited position at {exit_price} (P/L: {pl:.2f}, New Account Balance: {account_balance:.2f})")
                position_status = {}
                force_square_off = False
                open_position_data = None
                root.after(0, update_open_position_display)
                # Re-enable input fields when position is closed
                root.after(0, lambda: interval_combobox.config(state='readonly'))
            else:
                simulation_status = "Holding position; waiting for exit condition..."
                print(simulation_status)

        root.after(0, update_status)

        total_wait = 60
        interval_wait = 0.5
        waited = 0
        while waited < total_wait:
            if stop_event.is_set() or force_square_off:
                break
            time.sleep(interval_wait)
            waited += interval_wait
        if stop_event.is_set():
            break

    if in_position:
        open_position_data = {
            "entry_price": entry_price,
            "entry_date": entry_date,
            "entry_hour": entry_hour,
            "shares": shares,
            "account_balance": account_balance
        }
    else:
        open_position_data = None
        if os.path.exists("simulation_params.json"):
            os.remove("simulation_params.json")
            print("Deleted simulation_params.json as position is closed.")
    simulation_status = "Live trading simulation stopped."
    print(simulation_status)
    save_open_position()

# --------------------------
# Tkinter Front End
# --------------------------

simulation_thread = None
stop_event = None

def start_simulation():
    global simulation_thread, stop_event, open_position_data
    load_open_position()
    sim_params = load_simulation_params()
    if sim_params:
        ticker_entry.delete(0, tk.END)
        ticker_entry.insert(0, sim_params.get("ticker", ""))
        ema_short_entry.delete(0, tk.END)
        ema_short_entry.insert(0, str(sim_params.get("ema_short_period", "5")))
        ema_long_entry.delete(0, tk.END)
        ema_long_entry.insert(0, str(sim_params.get("ema_long_period", "13")))
        stoploss_entry.delete(0, tk.END)
        stoploss_entry.insert(0, str(sim_params.get("stoploss", "5")))
        target_entry.delete(0, tk.END)
        target_entry.insert(0, str(sim_params.get("target", "10")))
    if open_position_data is not None:
        ticker_entry.config(state='disabled')
        ema_short_entry.config(state='disabled')
        ema_long_entry.config(state='disabled')
        stoploss_entry.config(state='disabled')
        target_entry.config(state='disabled')
        print("Overnight open position detected; input boxes are disabled.")
    ticker = ticker_entry.get().strip().upper()
    try:
        ema_short_period = int(ema_short_entry.get().strip())
    except ValueError:
        ema_short_period = 5
    try:
        ema_long_period = int(ema_long_entry.get().strip())
    except ValueError:
        ema_long_period = 13
    try:
        stoploss = float(stoploss_entry.get().strip())
    except ValueError:
        stoploss = 5.0
    try:
        target = float(target_entry.get().strip())
    except ValueError:
        target = 10.0
    initial_capital = 10000.0
    sim_params = {
        "ticker": ticker,
        "ema_short_period": ema_short_period,
        "ema_long_period": ema_long_period,
        "stoploss": stoploss,
        "target": target
    }
    # Update the selected interval from the combobox
    global selected_interval
    selected_interval = interval_combobox.get()

    # Add interval to simulation parameters
    sim_params["interval"] = selected_interval
    save_simulation_params(sim_params)

    stop_event = threading.Event()
    simulation_thread = threading.Thread(target=live_trading, args=(ticker, ema_short_period, ema_long_period, initial_capital, stop_event, open_position_data, stoploss, target, selected_interval))
    simulation_thread.daemon = True
    simulation_thread.start()
    ticker_entry.config(state='disabled')
    ema_short_entry.config(state='disabled')
    ema_long_entry.config(state='disabled')
    stoploss_entry.config(state='disabled')
    target_entry.config(state='disabled')
    interval_combobox.config(state='disabled')  # Disable interval combobox
    start_button.config(state=tk.DISABLED)
    stop_button.config(state=tk.NORMAL)
    square_off_button.config(state=tk.NORMAL)
    print("Simulation started.")

def stop_simulation():
    global stop_event, simulation_thread
    if stop_event:
        stop_event.set()
    if simulation_thread:
        simulation_thread.join()
    start_button.config(state=tk.NORMAL)
    stop_button.config(state=tk.DISABLED)
    square_off_button.config(state=tk.DISABLED)
    if open_position_data is None:
        ticker_entry.config(state='normal')
        ema_short_entry.config(state='normal')
        ema_long_entry.config(state='normal')
        stoploss_entry.config(state='normal')
        target_entry.config(state='normal')
        interval_combobox.config(state='readonly')  # Re-enable interval combobox
    print("Simulation stopped.")

def square_off_position():
    global force_square_off, simulation_status, simulation_message
    if position_status:
        force_square_off = True
        simulation_status = "Square-off requested."
        simulation_message = simulation_status
        print("Square-off requested by user.")
        root.after(0, lambda: messagebox.showinfo("Square-Off", "Square-off requested: Exiting position."))
    
def update_status():
    if latest_status:
        try:
            price_val = float(latest_status.get('price', 0))
            price_str = f"{price_val:.2f}"
        except Exception:
            price_str = latest_status.get('price', 'N/A')
        status_text = f"Date: {latest_status.get('date', 'N/A')}, Time: {latest_status.get('hour', 'N/A')}, Price: {price_str}"
    else:
        status_text = "No data yet."
    status_label.config(text=status_text)
    sim_status_label.config(text=f"Status: {simulation_status}")
    msg_label.config(text=simulation_message)
    if open_position_data is not None:
        update_open_position_display()
    root.after(1000, update_status)

def on_closing():
    stop_simulation()
    save_open_position()
    root.destroy()

# --------------------------
# Tkinter GUI Setup
# --------------------------

root = tk.Tk()
root.title("EMA Live Paper Trading")
# root.geometry("800x600")  # Ensure a default visible size.
root.protocol("WM_DELETE_WINDOW", on_closing)

# Input Frame
input_frame = ttk.Frame(root, padding="10", borderwidth=3, relief="groove")
input_frame.grid(row=0, column=0, sticky="W", padx=10, pady=5)

ttk.Label(input_frame, text="Ticker Symbol:").grid(row=0, column=0, sticky="W", pady=2)
ticker_entry = ttk.Entry(input_frame, width=20)
ticker_entry.grid(row=0, column=1, pady=2)
ticker_entry.insert(0, "ETH-USD")

ttk.Label(input_frame, text="Short EMA Period:").grid(row=1, column=0, sticky="W", pady=2)
ema_short_entry = ttk.Entry(input_frame, width=20)
ema_short_entry.grid(row=1, column=1, pady=2)
ema_short_entry.insert(0, "5")

ttk.Label(input_frame, text="Long EMA Period:").grid(row=2, column=0, sticky="W", pady=2)
ema_long_entry = ttk.Entry(input_frame, width=20)
ema_long_entry.grid(row=2, column=1, pady=2)
ema_long_entry.insert(0, "13")

ttk.Label(input_frame, text="Stoploss (%) :").grid(row=3, column=0, sticky="W", pady=2)
stoploss_entry = ttk.Entry(input_frame, width=20)
stoploss_entry.grid(row=3, column=1, pady=2)
stoploss_entry.insert(0, "5")

ttk.Label(input_frame, text="Target (%) :").grid(row=4, column=0, sticky="W", pady=2)
target_entry = ttk.Entry(input_frame, width=20)
target_entry.grid(row=4, column=1, pady=2)
target_entry.insert(0, "10")

ttk.Label(input_frame, text="Interval:").grid(row=5, column=0, sticky="W", pady=2)
interval_combobox = ttk.Combobox(input_frame, values=["1wk", "1d", "1h", "15m"], state="readonly", width=18)
interval_combobox.grid(row=5, column=1, pady=2)
interval_combobox.set(selected_interval)  # Set default value from global variable
interval_combobox.bind("<<ComboboxSelected>>", lambda event: update_interval())



# Control Buttons
start_button = tk.Button(root, text="Start", command=start_simulation, relief=tk.RAISED, borderwidth=3, width=20, font=("Arial", 12, "bold"))
start_button.grid(row=1, column=0, pady=5)
stop_button = tk.Button(root, text="Stop", command=stop_simulation, state=tk.DISABLED, relief=tk.RAISED, borderwidth=3, width=20, font=("Arial", 12, "bold"))
stop_button.grid(row=2, column=0, pady=5)
square_off_button = tk.Button(root, text="Square Off", command=square_off_position, state=tk.DISABLED,
                              relief=tk.RAISED, borderwidth=3, width=15, font=("Arial", 12, "bold"))
square_off_button.grid(row=6, column=0, pady=5, sticky="e", padx=(0,10))

# Status Display Frames
status_frame = ttk.Frame(root, padding="10", borderwidth=3, relief="groove")
status_frame.grid(row=4, column=0, pady=5, sticky="ew", padx=10)
status_label = ttk.Label(status_frame, text="No data yet.", font=("Arial", 10, "bold"))
status_label.pack()
sim_status_label = ttk.Label(status_frame, text="Status: No signal yet.", font=("Arial", 10, "bold"))
sim_status_label.pack(pady=(5,0))
msg_label = ttk.Label(status_frame, text="No daily info yet.", font=("Arial", 10, "bold"))
msg_label.pack(pady=(5,0))

open_position_frame = ttk.Frame(root, padding="10", borderwidth=3, relief="groove")
open_position_frame.grid(row=5, column=0, pady=5, sticky="ew", padx=10)
ttk.Label(open_position_frame, text="Open Position", font=("Arial", 10, "bold")).grid(row=0, column=0, columnspan=6, pady=(0,5))
ttk.Label(open_position_frame, text="Signal", font=("Arial", 10, "bold")).grid(row=1, column=0, padx=5)
ttk.Label(open_position_frame, text="Entry Price", font=("Arial", 10, "bold")).grid(row=1, column=1, padx=5)
ttk.Label(open_position_frame, text="Shares", font=("Arial", 10, "bold")).grid(row=1, column=2, padx=5)
ttk.Label(open_position_frame, text="Current Value", font=("Arial", 10, "bold")).grid(row=1, column=3, padx=5)
ttk.Label(open_position_frame, text="P/L", font=("Arial", 10, "bold")).grid(row=1, column=4, padx=5)
pos_signal_val = ttk.Label(open_position_frame, text="N/A", font=("Arial", 10, "bold"))
pos_signal_val.grid(row=2, column=0, padx=5)
pos_price_val = ttk.Label(open_position_frame, text="N/A", font=("Arial", 10, "bold"))
pos_price_val.grid(row=2, column=1, padx=5)
pos_qty_val = ttk.Label(open_position_frame, text="N/A", font=("Arial", 10, "bold"))
pos_qty_val.grid(row=2, column=2, padx=5)
pos_value_val = ttk.Label(open_position_frame, text="N/A", font=("Arial", 10, "bold"))
pos_value_val.grid(row=2, column=3, padx=5)
pos_pl_val = ttk.Label(open_position_frame, text="N/A", font=("Arial", 10, "bold"))
pos_pl_val.grid(row=2, column=4, padx=5)

initial_setup()
root.after(1000, update_status)

if __name__ == '__main__':
    try:
        root.mainloop()
    except Exception as e:
        with open("error.log", "w") as f:
            f.write(str(e))
        raise
