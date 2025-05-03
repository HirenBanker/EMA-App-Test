import streamlit as st
import pandas as pd
import yfinance as yf
import datetime as dt
import time
import json
import os
import numpy as np
import matplotlib.pyplot as plt
import sys # Added for checking if frozen

# --- Configuration & Initial Setup ---
st.set_page_config(page_title="EMA/TSI Live Paper Trading", layout="wide")
st.title("📈 EMA/TSI Live Paper Trading Simulation")

# If frozen (packaged as exe), set working directory to the executable's directory.
# This might be less relevant for Streamlit but kept for consistency if packaged differently.
if getattr(sys, 'frozen', False):
    application_path = os.path.dirname(sys.executable)
    os.chdir(application_path)
    print(f"Running in frozen mode. Working directory set to: {application_path}")

# --- Persistence Functions ---

def load_open_position():
    if os.path.exists("open_position.json"):
        try:
            with open("open_position.json", "r") as f:
                return json.load(f)
        except Exception as e:
            st.error(f"Error loading open position: {e}")
            return None
    return None

def save_open_position(position_data):
    try:
        with open("open_position.json", "w") as f:
            json.dump(position_data, f)
        print("Saved open position to file.")
    except Exception as e:
        st.error(f"Error saving open position: {e}")

def load_simulation_params():
    if os.path.exists("simulation_params.json"):
        try:
            with open("simulation_params.json", "r") as f:
                return json.load(f)
        except Exception as e:
            st.error(f"Error loading simulation parameters: {e}")
            return None
    return None

def save_simulation_params(params):
    try:
        with open("simulation_params.json", "w") as f:
            json.dump(params, f)
        print("Saved simulation parameters to file.")
    except Exception as e:
        st.error(f"Error saving simulation parameters: {e}")

# --- Indicator Calculation Functions ---

def heikin_ashi(df):
    df = df.copy()
    df[['Open','High','Low','Close']] = df[['Open','High','Low','Close']].apply(pd.to_numeric, errors='coerce')
    ha = pd.DataFrame(index=df.index, columns=['HA_Open', 'HA_High', 'HA_Low', 'HA_Close'])
    ha['HA_Close'] = ((df['Open'] + df['High'] + df['Low'] + df['Close']) / 4).astype(float)
    if not ha.empty:
        ha.iloc[0, ha.columns.get_loc('HA_Open')] = (df['Open'].iloc[0] + df['Close'].iloc[0]) / 2
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
    diff = series.diff()
    abs_diff = diff.abs()
    ema1 = diff.ewm(span=r, adjust=False).mean()
    ema2 = ema1.ewm(span=s, adjust=False).mean()
    abs_ema1 = abs_diff.ewm(span=r, adjust=False).mean()
    abs_ema2 = abs_ema1.ewm(span=s, adjust=False).mean()
    # Avoid division by zero
    tsi = 100 * (ema2 / abs_ema2.replace(0, np.nan)) # Replace 0 with NaN before division
    tsi = tsi.fillna(0) # Fill resulting NaNs, e.g., with 0 or forward fill
    tsi_signal = tsi.ewm(span=signal_period, adjust=False).mean()
    return tsi, tsi_signal

# --- Live Data Update Function ---

def update_live_data(ticker, ema_short_period, ema_long_period, interval='1h'):
    try:
        data = yf.download(ticker, period="60d", interval=interval, progress=False)
        if data.empty:
            st.warning(f"No data available for {ticker} with interval {interval}.")
            return None
        data.index = pd.to_datetime(data.index)
        ha = heikin_ashi(data)
        if ha.empty or 'HA_Close' not in ha.columns:
             st.warning(f"Heikin Ashi calculation failed for {ticker}.")
             return None
        ha['EMA_short'] = ha['HA_Close'].ewm(span=ema_short_period, adjust=False).mean()
        ha['EMA_long'] = ha['HA_Close'].ewm(span=ema_long_period, adjust=False).mean()
        tsi, tsi_signal = calculate_tsi(ha['HA_Close'], r=25, s=13, signal_period=13)
        ha['TSI'] = tsi
        ha['TSI_Signal'] = tsi_signal
        return ha
    except Exception as e:
        st.error(f"Error fetching or processing data: {e}")
        return None

# --- Signal and Trade Recording Functions ---

def record_signal(file, date, hour, price):
    # Simplified: Just print for Streamlit, could save to file if needed
    print(f"SIGNAL recorded to {file}: {date} {hour} @ {price:.2f}")
    # If saving is desired:
    # row = pd.DataFrame({'Date': [date], 'Hour': [hour], 'Price': [round(price, 2)]})
    # try:
    #     if os.path.exists(file):
    #         existing_df = pd.read_pickle(file)
    #         combined_df = pd.concat([existing_df, row], ignore_index=True)
    #     else:
    #         combined_df = row
    #     combined_df.to_pickle(file)
    # except Exception as e:
    #     st.error(f"Error saving signal to {file}: {e}")

def record_trade(trade_file, entry_date, entry_hour, entry_price, exit_date, exit_hour, exit_price, pl, account_balance):
     # Simplified: Just print for Streamlit, could save to file if needed
    print(f"TRADE recorded to {trade_file}: Entry {entry_date} {entry_hour} @ {entry_price:.2f}, Exit {exit_date} {exit_hour} @ {exit_price:.2f}, P/L: {pl:.2f}, Balance: {account_balance:.2f}")
    # If saving is desired:
    # row = pd.DataFrame({ ... }) # As in original
    # try:
    #    # Save logic as in original
    # except Exception as e:
    #     st.error(f"Error saving trade to {trade_file}: {e}")

# --- Streamlit Session State Initialization ---

if 'running' not in st.session_state:
    st.session_state.running = False
if 'open_position' not in st.session_state:
    st.session_state.open_position = load_open_position() # Load persistent position
if 'params' not in st.session_state:
    st.session_state.params = load_simulation_params() # Load persistent params
if 'status_message' not in st.session_state:
    st.session_state.status_message = "Simulation not started."
if 'latest_data_info' not in st.session_state:
    st.session_state.latest_data_info = "No data yet."
if 'position_details' not in st.session_state:
    st.session_state.position_details = {}
if 'force_square_off' not in st.session_state:
    st.session_state.force_square_off = False
if 'initial_capital' not in st.session_state:
    st.session_state.initial_capital = 10000.0 # Default initial capital

# --- Sidebar for Inputs ---

st.sidebar.header("Simulation Parameters")

# Disable inputs if simulation is running or position is open
inputs_disabled = st.session_state.running or (st.session_state.open_position is not None)

# Load defaults from saved params or use hardcoded defaults
default_params = st.session_state.params or {}
default_ticker = default_params.get("ticker", "ETH-USD")
default_ema_short = default_params.get("ema_short_period", 5)
default_ema_long = default_params.get("ema_long_period", 13)
default_stoploss = default_params.get("stoploss", 5.0)
default_target = default_params.get("target", 10.0)
default_interval = default_params.get("interval", "1h")

ticker = st.sidebar.text_input("Ticker Symbol", value=default_ticker, disabled=inputs_disabled)
ema_short_period = st.sidebar.number_input("Short EMA Period", min_value=1, value=default_ema_short, disabled=inputs_disabled)
ema_long_period = st.sidebar.number_input("Long EMA Period", min_value=1, value=default_ema_long, disabled=inputs_disabled)
stoploss = st.sidebar.number_input("Stoploss (%)", min_value=0.1, value=default_stoploss, format="%.1f", disabled=inputs_disabled)
target = st.sidebar.number_input("Target (%)", min_value=0.1, value=default_target, format="%.1f", disabled=inputs_disabled)
interval = st.sidebar.selectbox("Interval", ["1wk", "1d", "1h", "15m", "5m", "1m"], index=["1wk", "1d", "1h", "15m", "5m", "1m"].index(default_interval), disabled=inputs_disabled)

# --- Control Buttons ---

col1, col2, col3 = st.sidebar.columns(3)

with col1:
    start_button = st.button("Start", disabled=st.session_state.running or inputs_disabled)
with col2:
    stop_button = st.button("Stop", disabled=not st.session_state.running)
with col3:
    square_off_button = st.button("Square Off", disabled=not st.session_state.running or st.session_state.open_position is None)

# --- Main Display Area ---

status_placeholder = st.empty()
position_placeholder = st.empty()

# --- Button Logic ---

if start_button:
    st.session_state.running = True
    st.session_state.force_square_off = False # Ensure square off flag is reset
    # Save current parameters for persistence
    current_params = {
        "ticker": ticker,
        "ema_short_period": ema_short_period,
        "ema_long_period": ema_long_period,
        "stoploss": stoploss,
        "target": target,
        "interval": interval
    }
    st.session_state.params = current_params
    save_simulation_params(current_params)
    st.session_state.status_message = "Simulation started..."
    st.rerun()

if stop_button:
    st.session_state.running = False
    st.session_state.status_message = "Simulation stopped by user."
    # Save open position if simulation is stopped while holding
    if st.session_state.open_position:
        save_open_position(st.session_state.open_position)
    else:
        # Clean up param file if stopped with no position
        if os.path.exists("simulation_params.json"):
            try:
                os.remove("simulation_params.json")
                print("Removed simulation_params.json as position was closed.")
            except Exception as e:
                st.error(f"Could not remove simulation_params.json: {e}")
    st.rerun()

if square_off_button:
    st.session_state.force_square_off = True
    st.session_state.status_message = "Square-off requested..."
    st.warning("Square-off requested. Position will be closed on the next data update.")
    # No rerun here, let the main loop handle it

# --- Simulation Loop (Executed if running) ---

if st.session_state.running:
    # Use saved parameters during the run
    run_params = st.session_state.params
    ticker = run_params['ticker']
    ema_short_period = run_params['ema_short_period']
    ema_long_period = run_params['ema_long_period']
    stoploss = run_params['stoploss']
    target = run_params['target']
    interval = run_params['interval']

    # Files for recording (optional, uncomment save logic in functions if needed)
    entry_file = "entry_signals.pkl"
    exit_file = "exit_signals.pkl"
    trade_file = "trade_data.pkl"

    # Get current position state from session_state
    open_pos = st.session_state.open_position
    in_position = open_pos is not None

    if in_position:
        entry_price = open_pos["entry_price"]
        entry_date = open_pos["entry_date"]
        entry_hour = open_pos["entry_hour"]
        shares = open_pos["shares"]
        # Account balance isn't actively tracked here like tkinter version, focus on P/L
    else:
        entry_price, entry_date, entry_hour, shares = None, None, None, 0.0

    # --- Data Fetch and Process ---
    ha_data = update_live_data(ticker, ema_short_period, ema_long_period, interval)

    if ha_data is None or len(ha_data) < 2:
        st.session_state.status_message = "Data update failed; waiting..."
        st.session_state.latest_data_info = "Data unavailable."
    else:
        prev_candle = ha_data.iloc[-2]
        current_candle = ha_data.iloc[-1]
        current_time = dt.datetime.now()
        current_date_str = current_time.strftime("%d-%b-%Y") # Use current time for recording
        current_hour_str = current_time.strftime("%H:%M:%S")
        current_price = float(current_candle['HA_Close']) # Use HA Close for logic

        st.session_state.latest_data_info = (
            f"Time: {current_hour_str}, "
            f"HA Close: {current_price:.2f}, "
            f"EMA({ema_short_period}): {current_candle['EMA_short']:.2f}, "
            f"EMA({ema_long_period}): {current_candle['EMA_long']:.2f}, "
            f"TSI: {current_candle['TSI']:.2f}, "
            f"Signal: {current_candle['TSI_Signal']:.2f}"
        )

        # --- Strategy Logic ---
        if not in_position:
            # Entry Condition: TSI positive, TSI above signal, Short EMA above Long EMA
            if (current_candle['TSI'] > 0) and \
               (current_candle['TSI'] > current_candle['TSI_Signal']) and \
               (current_candle['EMA_short'] > current_candle['EMA_long']):

                st.session_state.status_message = f"Entry signal detected @ {current_price:.2f}"
                st.success(st.session_state.status_message) # Show success message
                record_signal(entry_file, current_date_str, current_hour_str, current_price)

                entry_price = current_price
                entry_date = current_date_str
                entry_hour = current_hour_str
                # Simulate buying with fixed capital for simplicity in Streamlit context
                shares = st.session_state.initial_capital / entry_price

                st.session_state.open_position = {
                    "entry_price": entry_price,
                    "entry_date": entry_date,
                    "entry_hour": entry_hour,
                    "shares": shares,
                    "ticker": ticker # Store ticker in position data
                }
                save_open_position(st.session_state.open_position) # Persist immediately
                in_position = True # Update local flag for current run

            else:
                st.session_state.status_message = "No entry signal. Waiting..."

        else: # In position, check exit conditions
            current_value = shares * current_price
            pl_open = current_value - (shares * entry_price)

            # Update position details for display
            st.session_state.position_details = {
                "Signal": "BUY",
                "Entry Price": f"{entry_price:.2f}",
                "Shares": f"{shares:.4f}",
                "Current Value": f"{current_value:.2f}",
                "P/L": f"{pl_open:.2f}"
            }

            exit_condition = False
            exit_reason = ""

            # Exit Condition 1: Price drops below previous HA Low
            if current_price < float(prev_candle['HA_Low']):
                exit_condition = True
                exit_reason = "Exit: Price fell below previous HA low."
            # Exit Condition 2: Target Profit Reached
            elif current_price >= entry_price * (1 + target / 100):
                exit_condition = True
                exit_reason = f"Exit: Target profit ({target}%) reached."
            # Exit Condition 3: Stop Loss Hit
            elif current_price <= entry_price * (1 - stoploss / 100):
                exit_condition = True
                exit_reason = f"Exit: Stop loss ({stoploss}%) triggered."
            # Exit Condition 4: Manual Square Off
            elif st.session_state.force_square_off:
                exit_condition = True
                exit_reason = "Exit: Manual square-off triggered."

            if exit_condition:
                st.session_state.status_message = f"{exit_reason} Exiting @ {current_price:.2f}"
                st.info(st.session_state.status_message) # Show info message
                record_signal(exit_file, current_date_str, current_hour_str, current_price)

                exit_price = current_price
                trade_value = shares * exit_price
                pl = trade_value - (shares * entry_price)
                # Simplified account balance update for recording
                final_balance = st.session_state.initial_capital + pl

                record_trade(trade_file, entry_date, entry_hour, entry_price, current_date_str, current_hour_str, exit_price, pl, final_balance)

                # Clear position state
                st.session_state.open_position = None
                st.session_state.position_details = {}
                st.session_state.force_square_off = False # Reset flag
                save_open_position(None) # Update persistence file
                in_position = False # Update local flag

                # Clean up param file only if position is closed naturally (not stopped)
                if os.path.exists("simulation_params.json"):
                     try:
                         os.remove("simulation_params.json")
                         print("Removed simulation_params.json as position was closed.")
                     except Exception as e:
                         st.error(f"Could not remove simulation_params.json: {e}")

            else:
                st.session_state.status_message = f"Holding position. P/L: {pl_open:.2f}"

    # --- Update UI ---
    status_placeholder.status(f"{st.session_state.status_message}\n\n{st.session_state.latest_data_info}", state="running" if st.session_state.running else "complete")

    if st.session_state.open_position:
        pos = st.session_state.position_details
        cols = position_placeholder.columns(5)
        cols[0].metric("Signal", pos.get("Signal", "N/A"))
        cols[1].metric("Entry Price", pos.get("Entry Price", "N/A"))
        cols[2].metric("Shares", pos.get("Shares", "N/A"))
        cols[3].metric("Current Value", pos.get("Current Value", "N/A"))
        cols[4].metric("P/L", pos.get("P/L", "N/A"))
    else:
        position_placeholder.info("No open position.")

    # --- Schedule Next Run ---
    time.sleep(60) # Wait for 60 seconds
    st.rerun()

else: # Not running
    # Display final status or initial message
    status_placeholder.status(f"{st.session_state.status_message}\n\n{st.session_state.latest_data_info}", state="complete")

    # Display open position if loaded from file and not running
    if st.session_state.open_position:
        pos = st.session_state.open_position
        # Calculate display details if needed (P/L requires current price fetch)
        # For simplicity, just show entry details when not running actively
        cols = position_placeholder.columns(5)
        cols[0].metric("Signal", "BUY (Loaded)")
        cols[1].metric("Entry Price", f"{pos.get('entry_price', 0):.2f}")
        cols[2].metric("Shares", f"{pos.get('shares', 0):.4f}")
        cols[3].metric("Current Value", "N/A (Not Running)")
        cols[4].metric("P/L", "N/A (Not Running)")
        st.info("Loaded an existing open position. Press Start to resume simulation.")
    else:
        position_placeholder.info("No open position.")
