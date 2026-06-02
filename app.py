from __future__ import annotations

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
import matplotlib

from model import AsphaltModelConfig, estimate_asphalt_temperature, find_recommended_windows
from weather import WeatherRequest, fetch_hourly_weather

matplotlib.rcParams["font.family"] = "Meiryo"
matplotlib.rcParams["axes.unicode_minus"] = False

st.set_page_config(
    page_title="犬の散歩用アスファルト温度予測",
    page_icon="🐕",
    layout="wide",
)

st.title("犬の散歩用アスファルト温度予測")
st.caption("気象予報から、アスファルト路面温度を安全寄りに推定します。")

latitude = 35.2813
longitude = 139.6722
forecast_days = 2
max_walk_temp = 35.0

#with st.sidebar:
    #st.header("地点設定")

    #st.header("推定係数")
    #max_solar_gain_c = st.slider("日射による最大上昇", 5.0, 40.0, 24.0, 1.0)
    #wind_cooling_factor = st.slider("風による冷却係数", 0.0, 1.0, 0.22, 0.01)
    #rain_cooling_factor = st.slider("雨による冷却係数", 0.0, 10.0, 4.0, 0.5)
    #heat_memory = st.slider("蓄熱の残りやすさ", 0.0, 0.95, 0.62, 0.01)
    #safety_margin_c = st.slider("安全マージン", 0.0, 8.0, 2.0, 0.5)

    #max_walk_temp = st.slider("推奨散歩の上限温度", 25.0, 45.0, 35.0, 1.0)

request = WeatherRequest(
    latitude=latitude,
    longitude=longitude,
    forecast_days=forecast_days,
)

config = AsphaltModelConfig(
    #max_solar_gain_c=max_solar_gain_c,
    #wind_cooling_factor=wind_cooling_factor,
    #rain_cooling_factor=rain_cooling_factor,
    #heat_memory=heat_memory,
    #safety_margin_c=safety_margin_c,
)

try:
    weather_df = fetch_hourly_weather(request)
    result_df = estimate_asphalt_temperature(weather_df, config)
except Exception as exc:
    st.error("気象データの取得または計算に失敗しました。")
    st.exception(exc)
    st.stop()

# 現在以降だけ表示
now = pd.Timestamp.now(tz="Asia/Tokyo").tz_localize(None)
display_df = result_df[result_df["time"] >= now.floor("h")].copy()

latest = display_df.iloc[0]

col1, col2, col3, col4 = st.columns(4)
col1.metric("現在以降の最初の気温", f"{latest['air_temp_c']:.1f}℃")
col2.metric("推定路面温度", f"{latest['asphalt_temp_c']:.1f}℃")
col3.metric("判定", latest["risk_level"])
col4.metric("散歩目安", latest["walk_judgement"])

st.subheader("推奨散歩時間帯")
windows = find_recommended_windows(display_df, max_temp_c=max_walk_temp)

if windows:
    for window in windows:
        st.success(window)
else:
    st.warning("指定した上限温度未満の時間帯がありません。早朝・夜間、または実測確認を検討してください。")

st.subheader("アスファルト温度予測グラフ")

fig, ax = plt.subplots(figsize=(12, 5))
ax.plot(
    display_df["time"],
    display_df["air_temp_c"],
    marker="o",
    linewidth=2,
    color="#1976D2",
    label="気温",
)

ax.plot(
    display_df["time"],
    display_df["asphalt_temp_c"],
    marker="o",
    linewidth=2.8,
    color="#E65100",
    label="Asphalt temperature forecast",
)

# 判定帯
ax.axhspan(0, 30, color="#E8F5E9", alpha=0.35, label="Safe")
ax.axhspan(30, 40, color="#FFF9C4", alpha=0.45, label="Caution")
ax.axhspan(40, 55, color="#FFE0B2", alpha=0.50, label="Danger")
ax.axhspan(55, 90, color="#FFCDD2", alpha=0.55, label="Very Dangerous")

# 境界線
ax.axhline(30, color="#66BB6A", linestyle="--", linewidth=1.2, alpha=0.8)
ax.axhline(40, color="#F9A825", linestyle="--", linewidth=1.2, alpha=0.8)
ax.axhline(55, color="#E53935", linestyle="--", linewidth=1.2, alpha=0.8)

ax.set_xlabel("Time")
ax.set_ylabel("Temperature (°C)")
y_min = min(display_df["air_temp_c"].min(), display_df["asphalt_temp_c"].min()) - 5
y_max = max(display_df["air_temp_c"].max(), display_df["asphalt_temp_c"].max()) + 5

# 判定帯の境界が必要なら少しだけ含める
y_min = max(0, y_min)
y_max = max(y_max, 40)

ax.set_ylim(y_min, y_max)
ax.grid(True, alpha=0.3)
ax.legend(loc="upper left", framealpha=0.75)
fig.autofmt_xdate()

st.pyplot(fig)

with st.expander("時間別データを見る"):
    st.dataframe(
        display_df[
            [
                "time",
                "air_temp_c",
                "asphalt_temp_c",
                "risk_level",
                "walk_judgement",
                "humidity_pct",
                "precip_mm",
                "cloud_cover_pct",
                "wind_speed_kmh",
                "shortwave_radiation_wm2",
            ]
        ],
        width="stretch",
    )

st.info(
    "この推定は実測値ではありません。特に夏場は、実際の路面を手で触るか赤外線温度計で確認してください。"
)
