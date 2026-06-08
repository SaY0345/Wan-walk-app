from __future__ import annotations

import pandas as pd
import streamlit as st
#import requests
from datetime import date

import plotly.graph_objects as go
#from streamlit_geolocation import streamlit_geolocation

from model import AsphaltModelConfig, estimate_asphalt_temperature, find_recommended_windows
from weather import WeatherRequest, fetch_hourly_weather

st.set_page_config(
    page_title="犬の散歩用アスファルト温度予測",
    page_icon="assets/shiba_logo.png",
    layout="wide",
)

st.markdown("""
<style>

@import url('https://fonts.googleapis.com/css2?family=M+PLUS+Rounded+1c:wght@400;700&display=swap');

html, body, [class*="css"] {
    font-family: 'M PLUS Rounded 1c', sans-serif;
}

.stApp {
    background-color: #F4FBF4;
}

</style>
""", unsafe_allow_html=True)

locations = {
    "横須賀市": {"lat": 35.2813, "lon": 139.6722},
    "横浜市": {"lat": 35.4437, "lon": 139.6380},
    "鎌倉市": {"lat": 35.3192, "lon": 139.5467},
    "藤沢市": {"lat": 35.3392, "lon": 139.4900},
}

#use_current_location = st.checkbox("現在地を使う")

#if use_current_location:
#    location = streamlit_geolocation()#

#    if location and location.get("latitude") and location.get("longitude"):
#        latitude = location["latitude"]
#        longitude = location["longitude"]
#        location_name = f"{reverse_geocode(latitude, longitude)}（現在地）"
#    else:
#        st.info("位置情報の取得を許可してください。取得できない場合は地点選択を使います。")
#        location_name = st.selectbox("地点を選択", list(locations.keys()), index=0)
#        latitude = locations[location_name]["lat"]
#        longitude = locations[location_name]["lon"]
#else:
#    location_name = st.selectbox("地点を選択", list(locations.keys()), index=0)
#    latitude = locations[location_name]["lat"]
#    longitude = locations[location_name]["lon"]

forecast_days = 2
max_walk_temp = 30.0

left, center, right = st.columns([1, 3, 1])

st.title("🐕 Wan Walk")
st.caption("犬の散歩向け・路面温度予測")

with st.expander("📍 地点設定", expanded=False):
    location_name = st.selectbox(
        "📍 地点を選択",
        list(locations.keys()),
        index=0,
    )
    
    latitude = locations[location_name]["lat"]
    longitude = locations[location_name]["lon"]

st.caption(f"📍 {location_name}")

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

status_icon = {
    "安全": "🟢",
    "注意": "🟡",
    "危険": "🟠",
    }.get(current_risk, "🔴")

status_message = {
    "安全": "今なら散歩しやすい",
    "注意": "短時間の散歩なら可",
    "危険": "路面温度に注意",
    }.get(current_risk, "散歩はおすすめしません")

st.subheader(f"🐾 現在の状況（{current_time}時点）")

now_time = pd.Timestamp.now()

future_safe_df = display_df[
    (display_df["time"] > now_time)
    & (display_df["asphalt_temp_c"] <= max_walk_temp)
]

with st.container(border=True):
    col1, col2 = st.columns(2)

    with col1:
        st.metric("🌡 気温", f"{current_air:.1f}℃")

    with col2:
        st.metric("🐾 路面温度", f"{current_asphalt:.1f}℃")

    if current_risk == "安全":
        st.success("🟢 安全：今なら散歩しやすい")
    elif current_risk == "注意":
        st.warning("🟡 注意：短時間の散歩なら可")
    elif current_risk == "危険":
        st.error("🟠 危険：路面温度に注意")
    else:
        st.error("🔴 非常に危険：散歩はおすすめしません")

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

if today_df.empty:
    today_df = display_df

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

st.subheader("🐕 おすすめ散歩時間")

windows = find_recommended_windows(
    display_df,
    max_temp_c=max_walk_temp,
)

if windows:
    st.success(
        f"🟢 次のおすすめ\n\n{windows[0]}"
    )
    if len(windows) > 1:
        with st.expander("その他のおすすめ時間帯"):
            for w in windows[1:]:
                st.write(w)
else:
    st.error("推奨できる時間帯はありません")

st.subheader("📈 路面温度の推移")
st.caption("左右にドラッグして時間帯を確認できます")

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
    height=360,
    dragmode="pan",
    margin=dict(l=10, r=10, t=30, b=10),
    yaxis=dict(range=[y_min, y_max]),
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
