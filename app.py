from __future__ import annotations

import pandas as pd
import streamlit as st
import requests

import plotly.graph_objects as go
from streamlit_geolocation import streamlit_geolocation

from model import AsphaltModelConfig, estimate_asphalt_temperature, find_recommended_windows
from weather import WeatherRequest, fetch_hourly_weather

def reverse_geocode(lat: float, lon: float) -> str:
    url = "https://nominatim.openstreetmap.org/reverse"

    params = {
        "lat": lat,
        "lon": lon,
        "format": "json",
        "zoom": 10,
        "addressdetails": 1,
    }

    headers = {
        "User-Agent": "WanWalkApp"
    }

    try:
        response = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        address = data.get("address", {})

        return (
            address.get("city")
            or address.get("town")
            or address.get("village")
            or address.get("municipality")
            or address.get("county")
            or address.get("state_district")
            or address.get("state")
            or data.get("display_name")
            or "現在地"
        )

    #except Exception:
    #    return "現在地"
    except Exception as e:
        st.error(f"逆ジオコーディングに失敗しました: {e}")
        return "現在地"

st.set_page_config(
    page_title="犬の散歩用アスファルト温度予測",
    page_icon="🐕",
    layout="wide",
)

locations = {
    "横須賀市": {"lat": 35.2813, "lon": 139.6722},
    "横浜市": {"lat": 35.4437, "lon": 139.6380},
    "鎌倉市": {"lat": 35.3192, "lon": 139.5467},
    "藤沢市": {"lat": 35.3392, "lon": 139.4900},
}

st.subheader("📍 地点設定")

use_current_location = st.checkbox("現在地を使う")

if use_current_location:
    location = streamlit_geolocation()

    if location and location.get("latitude") and location.get("longitude"):
        latitude = location["latitude"]
        longitude = location["longitude"]
        location_name = f"{reverse_geocode(latitude, longitude)}（現在地）"
    else:
        st.info("位置情報の取得を許可してください。取得できない場合は地点選択を使います。")
        location_name = st.selectbox("地点を選択", list(locations.keys()), index=0)
        latitude = locations[location_name]["lat"]
        longitude = locations[location_name]["lon"]
else:
    location_name = st.selectbox("地点を選択", list(locations.keys()), index=0)
    latitude = locations[location_name]["lat"]
    longitude = locations[location_name]["lon"]

forecast_days = 2
max_walk_temp = 30.0

st.title("🐕 Wan Walk")
st.caption("犬の散歩向け・路面温度予測")
st.caption(f"📍 {location_name}")

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

current = display_df.iloc[0]

current_air = current["air_temp_c"]
current_asphalt = current["asphalt_temp_c"]
current_risk = current["risk_level"]
current_judgement = current["walk_judgement"]
current_time = current["time"].strftime("%m/%d %H:%M")

st.subheader(f"🐾 現在の状況（{current_time}時点）")

from datetime import date

col1, col2 = st.columns(2)

with col1:
    st.metric("🌡 現在の気温", f"{current_air:.1f}℃")

with col2:
    st.metric("🐾 現在の推定路面温度", f"{current_asphalt:.1f}℃")

if current_risk == "安全":
    st.success("🐾 今なら散歩しやすい")
elif current_risk == "注意":
    st.warning("🐾 短時間の散歩なら可")
elif current_risk == "危険":
    st.error("🐾 路面温度に注意")
else:
    st.error("🐾 散歩はおすすめしません")

now_time = pd.Timestamp.now()

future_safe_df = display_df[
    (display_df["time"] > now_time)
    & (display_df["asphalt_temp_c"] <= max_walk_temp)
]

if current_asphalt <= max_walk_temp:
    st.info("このあともしばらく散歩しやすい予想です")
elif not future_safe_df.empty:
    next_safe_time = future_safe_df.iloc[0]["time"]
    hours_until = (next_safe_time - now_time).total_seconds() / 3600

    st.info(
        f"次に{max_walk_temp:.0f}℃以下になる予想："
        f"{next_safe_time:%H:%M}頃\n\n"
        f"あと約{hours_until:.1f}時間"
    )
else:
    st.warning("予報期間内に散歩しやすい時間帯は見つかりません")

today_df = display_df[
    display_df["time"].dt.date == date.today()
]

today_max = today_df["asphalt_temp_c"].max()
today_min = today_df["asphalt_temp_c"].min()

st.subheader("📊 今日の路面温度予想")

col1, col2 = st.columns(2)

with col1:
    st.metric(
        "🔥 最高",
        f"{today_max:.1f}℃"
    )

with col2:
    st.metric(
        "❄️ 最低",
        f"{today_min:.1f}℃"
    )

latest = display_df.iloc[0]

st.subheader("🐕 おすすめ散歩時間")

windows = find_recommended_windows(
    display_df,
    max_temp_c=max_walk_temp,
)

if windows:
    for w in windows:
        st.success(f"🐾 {w}")
else:
    st.error("推奨できる時間帯はありません")

st.subheader("アスファルト温度予測グラフ")

fig = go.Figure()

# 判定帯
fig.add_hrect(y0=0, y1=30, fillcolor="#E8F5E9", opacity=0.35, line_width=0)
fig.add_hrect(y0=30, y1=40, fillcolor="#FFF9C4", opacity=0.45, line_width=0)
fig.add_hrect(y0=40, y1=55, fillcolor="#FFE0B2", opacity=0.50, line_width=0)
fig.add_hrect(y0=55, y1=90, fillcolor="#FFCDD2", opacity=0.55, line_width=0)

# 境界線
fig.add_hline(y=30, line_dash="dash", line_color="#66BB6A", line_width=1)
fig.add_hline(y=40, line_dash="dash", line_color="#F9A825", line_width=1)
fig.add_hline(y=55, line_dash="dash", line_color="#E53935", line_width=1)

# 気温
fig.add_trace(
    go.Scatter(
        x=display_df["time"],
        y=display_df["air_temp_c"],
        mode="lines+markers",
        name="Air temp",
        line=dict(color="#1976D2", width=2),
        marker=dict(size=6),
    )
)

# 推定アスファルト温度
fig.add_trace(
    go.Scatter(
        x=display_df["time"],
        y=display_df["asphalt_temp_c"],
        mode="lines+markers",
        name="Asphalt temperature forecast",
        line=dict(color="#E65100", width=3),
        marker=dict(size=6),
    )
)

y_min = min(display_df["air_temp_c"].min(), display_df["asphalt_temp_c"].min()) - 5
y_max = max(display_df["air_temp_c"].max(), display_df["asphalt_temp_c"].max()) + 5

y_min = max(0, y_min)
y_max = min(60, max(y_max, 40))

fig.update_layout(
    yaxis=dict(
        range=[y_min, y_max]
    )
)

fig.update_layout(
    height=360,
    dragmode="pan",
    margin=dict(l=10, r=10, t=30, b=10),
    legend=dict(
        orientation="h",
        yanchor="bottom",
        y=1.02,
        xanchor="left",
        x=0,
    ),
)

initial_hours = 8

fig.update_xaxes(
    range=[
        display_df["time"].iloc[0],
        display_df["time"].iloc[min(initial_hours, len(display_df) - 1)],
    ],
    tickformat="%H:%M",
)

fig.update_layout(
    dragmode="pan",
)

st.plotly_chart(fig, width="stretch")

detail_df = display_df[
    [
        "time",
        "air_temp_c",
        "asphalt_temp_c",
        "risk_level",
        "walk_judgement",
    ]
].copy()

detail_df = detail_df.rename(
    columns={
        "time": "時刻",
        "air_temp_c": "気温",
        "asphalt_temp_c": "路面温度",
        "risk_level": "判定",
        "walk_judgement": "散歩目安",
    }
)

with st.expander("時間別データを見る"):
    st.dataframe(detail_df, width="stretch")

st.info(
    "この推定は実測値ではありません。特に夏場は、実際の路面を手で触るか赤外線温度計で確認してください。"
)
