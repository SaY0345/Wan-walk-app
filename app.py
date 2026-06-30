from __future__ import annotations

import pandas as pd
import streamlit as st
#import requests

import plotly.graph_objects as go
#from streamlit_geolocation import streamlit_geolocation

from wanwalk_measurements import (
    DEFAULT_SHEET_WORKSHEET,
    MANUAL_SOURCE_LABEL,
    append_measurement,
    append_measurement_to_apps_script,
    append_measurement_to_google_sheet,
    build_calibration_summary,
    build_coefficient_review,
    get_measurement_storage_status,
    load_apps_script_measurements,
    load_google_sheet_measurements,
    load_measurements,
    summarize_measurements,
    summarize_source_counts,
)
from model import AsphaltModelConfig, estimate_asphalt_temperature, find_recommended_windows
from weather import WeatherRequest, get_hourly_weather

st.set_page_config(
    page_title="犬の散歩用アスファルト温度予測",
    page_icon="🐾",
    layout="wide",
)


def resolve_measurement_storage():
    wanwalk_secrets = st.secrets.get("wanwalk", {})
    apps_script_url = wanwalk_secrets.get("apps_script_url")
    if apps_script_url:
        return {
            "backend": "apps-script",
            "service_account_info": None,
            "spreadsheet_id": None,
            "worksheet_name": wanwalk_secrets.get("worksheet_name", DEFAULT_SHEET_WORKSHEET),
            "apps_script_url": apps_script_url,
            "apps_script_token": wanwalk_secrets.get("apps_script_token"),
        }

    if (
        "google_service_account" in st.secrets
        and "wanwalk" in st.secrets
        and "spreadsheet_id" in st.secrets["wanwalk"]
    ):
        worksheet_name = st.secrets["wanwalk"].get("worksheet_name", DEFAULT_SHEET_WORKSHEET)
        return {
            "backend": "google-sheets",
            "service_account_info": dict(st.secrets["google_service_account"]),
            "spreadsheet_id": st.secrets["wanwalk"]["spreadsheet_id"],
            "worksheet_name": worksheet_name,
            "apps_script_url": None,
            "apps_script_token": None,
        }

    return {
        "backend": "local-csv",
        "service_account_info": None,
        "spreadsheet_id": None,
        "worksheet_name": DEFAULT_SHEET_WORKSHEET,
        "apps_script_url": None,
        "apps_script_token": None,
    }

st.markdown("""
<style>

@import url('https://fonts.googleapis.com/css2?family=M+PLUS+Rounded+1c:wght@400;700&display=swap');

html, body, [class*="css"] {
    font-family: 'M PLUS Rounded 1c', sans-serif;
}

.stApp {
    background-color: #F4FBF4;
}
            
.block-container {
    padding-top: 1rem;
    padding-bottom: 1rem;
}

.stApp::before {
    content: "🐾";
    position: fixed;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    font-size: 28rem;
    color: #66BB6A;
    opacity: 0.03;
    z-index: 0;
    pointer-events: none;
}

.block-container {
    position: relative;
    z-index: 1;
}

[data-testid="stVerticalBlockBorderWrapper"] {
    border-radius: 20px !important;
    background: rgba(255,255,255,0.75);
}

[data-testid="stVerticalBlockBorderWrapper"] {
    border-radius: 20px !important;
    box-shadow: 0 8px 24px rgba(0,0,0,0.15) !important;
}

</style>
""", unsafe_allow_html=True)

if st.session_state.pop("measurement_saved", False):
    st.success("実測値を保存しました")

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

st.markdown("## Wan Walk")
st.caption("犬の散歩向け・路面温度予測")

default_location = st.session_state.get("location_name", "横須賀市")

st.markdown(
    f"""
    <div style="
        text-align:center;
        color:#5E7D5E;
        font-size:1rem;
        font-weight:600;
        margin-top:-8px;
        margin-bottom:12px;
    ">
        📍 {default_location}
    </div>
    """,
    unsafe_allow_html=True,
)

with st.expander("📍 地点変更", expanded=False):
    location_name = st.selectbox(
        "地点を選択",
        list(locations.keys()),
        index=list(locations.keys()).index(default_location),
        key="location_name",
    )

latitude = locations[location_name]["lat"]
longitude = locations[location_name]["lon"]

config = AsphaltModelConfig(
    #max_solar_gain_c=max_solar_gain_c,
    #wind_cooling_factor=wind_cooling_factor,
    #rain_cooling_factor=rain_cooling_factor,
    #heat_memory=heat_memory,
    #safety_margin_c=safety_margin_c,
)

measurement_storage = resolve_measurement_storage()
storage_warning = ""
extra_measurement_frames: list[pd.DataFrame] = []
include_local_measurements = measurement_storage["backend"] not in {"google-sheets", "apps-script"}

if measurement_storage["backend"] == "google-sheets":
    try:
        extra_measurement_frames.append(
            load_google_sheet_measurements(
                measurement_storage["service_account_info"],
                measurement_storage["spreadsheet_id"],
                measurement_storage["worksheet_name"],
            )
        )
        include_local_measurements = False
    except Exception:
        storage_warning = (
            "Google Sheets の読み込みに失敗したため、"
            "ローカルCSV保存へ一時的にフォールバックしています"
        )
        include_local_measurements = True
        measurement_storage = {
            "backend": "local-csv",
            "service_account_info": None,
            "spreadsheet_id": None,
            "worksheet_name": DEFAULT_SHEET_WORKSHEET,
            "apps_script_url": None,
            "apps_script_token": None,
        }
elif measurement_storage["backend"] == "apps-script":
    try:
        extra_measurement_frames.append(
            load_apps_script_measurements(
                measurement_storage["apps_script_url"],
                measurement_storage["apps_script_token"],
            )
        )
        include_local_measurements = False
    except Exception:
        storage_warning = (
            "Apps Script の読み込みに失敗したため、"
            "ローカルCSV保存へ一時的にフォールバックしています"
        )
        include_local_measurements = True
        measurement_storage = {
            "backend": "local-csv",
            "service_account_info": None,
            "spreadsheet_id": None,
            "worksheet_name": DEFAULT_SHEET_WORKSHEET,
            "apps_script_url": None,
            "apps_script_token": None,
        }

measurement_history = load_measurements(
    include_local=include_local_measurements,
    extra_frames=extra_measurement_frames,
)
calibration = build_calibration_summary(measurement_history, location_name)
coefficient_review = build_coefficient_review(
    measurement_history,
    location_name,
    base_config=config,
)
active_config = coefficient_review.recommended_config if coefficient_review.is_active else config
imported_count, manual_count = summarize_source_counts(measurement_history)
measurement_storage_status = get_measurement_storage_status(
    measurement_storage["backend"],
    spreadsheet_id=measurement_storage["spreadsheet_id"],
    worksheet_name=measurement_storage["worksheet_name"],
    web_app_url=measurement_storage["apps_script_url"],
)
weather_request = WeatherRequest(
    latitude=latitude,
    longitude=longitude,
    forecast_days=forecast_days,
)

try:
    weather_result = get_hourly_weather(weather_request)
    weather_df = weather_result.weather_df
    result_df = estimate_asphalt_temperature(
        weather_df,
        active_config,
        calibration_slope=calibration.slope,
        calibration_intercept_c=calibration.intercept_c,
    )
except Exception:
    st.error("気象データを取得できませんでした。時間をおいて再度お試しください。")
    st.stop()

# 現在以降だけ表示
now = pd.Timestamp.now(tz="Asia/Tokyo").tz_localize(None)
display_df = result_df[result_df["time"] >= now.floor("h")].copy()
if display_df.empty:
    display_df = result_df.tail(24).copy()

current = display_df.iloc[0]

current_air = current["air_temp_c"]
current_base_asphalt = current["base_asphalt_temp_c"]
current_asphalt = current["asphalt_temp_c"]
current_risk = current["risk_level"]
current_time = current["time"].strftime("%m/%d %H:%M")

st.subheader(f"🐾 現在の状況（{current_time}時点）")

weather_fetched_local = weather_result.fetched_at.tz_convert("Asia/Tokyo")
if weather_result.is_stale_fallback:
    st.warning(
        f"最新の気象データ再取得に失敗したため、"
        f"{weather_fetched_local:%m/%d %H:%M} 取得のキャッシュで表示しています"
    )
else:
    st.caption(
        f"気象データ更新: {weather_fetched_local:%m/%d %H:%M}"
        f" ({weather_result.source}, 経過 {weather_result.age_minutes:.0f}分)"
    )

if storage_warning:
    st.warning(storage_warning)
elif measurement_storage_status.is_persistent:
    st.caption(f"実測保存先: {measurement_storage_status.label} ({measurement_storage_status.detail})")
else:
    st.caption(
        "実測保存先: ローカルCSV"
        "（Streamlit Community Cloud で使う場合は Apps Script または Google Sheets 設定を推奨）"
    )

now_time = now

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

if calibration.is_active:
    st.caption(
        f"実測補正: {calibration.scope_label} {calibration.sample_count}件"
        f"（取込 {calibration.imported_sample_count}件 / 手入力 {calibration.manual_sample_count}件）をもとに "
        f"{calibration.method_label} {calibration.equation_text} を適用中 "
        f"（平均ずれ {calibration.baseline_mae_c:.1f}℃ → {calibration.mae_c:.1f}℃）"
    )
elif calibration.sample_count:
    st.caption(
        f"実測 {calibration.sample_count}件を確認済みです。"
        f"現在の予測の平均ずれは {calibration.baseline_mae_c:.1f}℃ でした"
    )
else:
    asphalt_count = imported_count + manual_count
    remaining = max(0, 3 - asphalt_count)
    st.caption(
        "アスファルト実測が3件以上たまると補正が有効になります"
        + (f"（あと{remaining}件）" if remaining else "")
    )

if coefficient_review.is_active:
    st.caption(
        f"係数再検証: {coefficient_review.scope_label} {coefficient_review.sample_count}件をもとに "
        f"平均ずれ {coefficient_review.baseline_mae_c:.1f}℃ → {coefficient_review.reviewed_mae_c:.1f}℃ "
        f"となる係数を適用中"
    )
elif coefficient_review.sample_count:
    remaining = max(0, 8 - coefficient_review.sample_count)
    st.caption(
        f"係数再検証用の手入力実測は {coefficient_review.sample_count}件です"
        + (f"（あと{remaining}件で自動見直し開始）" if remaining else "")
    )

today_df = display_df[
    display_df["time"].dt.date == now.date()
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
st.caption("路面温度が30℃以下になる時間帯です")

windows = find_recommended_windows(
    display_df,
    max_temp_c=max_walk_temp,
)

if windows:
    st.success(
        f"🐾 次のおすすめ時間帯\n\n{windows[0]}"
    )

    if len(windows) > 1:
        with st.expander("その他のおすすめ時間帯"):
            for w in windows[1:]:
                st.write(f"🐾 {w}")
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

with st.expander("🧪 係数の再検証状況", expanded=False):
    review_col1, review_col2 = st.columns(2)
    review_col1.metric("手入力実測", f"{coefficient_review.sample_count}件")
    review_col2.metric(
        "改善量",
        f"{coefficient_review.improvement_c:+.1f}℃" if coefficient_review.sample_count else "-",
    )

    if coefficient_review.sample_count:
        st.caption(coefficient_review.scope_label or "手入力実測")
        review_table = pd.DataFrame(
            [
                {
                    "係数": "日射上乗せ",
                    "現在": round(config.max_solar_gain_c, 2),
                    "推奨": round(coefficient_review.recommended_config.max_solar_gain_c, 2),
                    "差分": coefficient_review.delta_solar_gain_c,
                },
                {
                    "係数": "風冷却",
                    "現在": round(config.wind_cooling_factor, 3),
                    "推奨": round(coefficient_review.recommended_config.wind_cooling_factor, 3),
                    "差分": coefficient_review.delta_wind_cooling_factor,
                },
                {
                    "係数": "雨冷却",
                    "現在": round(config.rain_cooling_factor, 3),
                    "推奨": round(coefficient_review.recommended_config.rain_cooling_factor, 3),
                    "差分": coefficient_review.delta_rain_cooling_factor,
                },
                {
                    "係数": "夜間冷却",
                    "現在": round(config.night_cooling_c, 2),
                    "推奨": round(coefficient_review.recommended_config.night_cooling_c, 2),
                    "差分": coefficient_review.delta_night_cooling_c,
                },
                {
                    "係数": "安全マージン",
                    "現在": round(config.safety_margin_c, 2),
                    "推奨": round(coefficient_review.recommended_config.safety_margin_c, 2),
                    "差分": coefficient_review.delta_safety_margin_c,
                },
            ]
        )
        st.dataframe(review_table, width="stretch", hide_index=True)
        st.write(
            f"補正前平均ずれ: {coefficient_review.baseline_mae_c:.1f}℃ / "
            f"再検証後見込み: {coefficient_review.reviewed_mae_c:.1f}℃"
        )
    else:
        st.write("手入力の実測データがまだ少ないため、係数の自動見直しは始まっていません。")

st.subheader("📝 実測メモ")

with st.expander("実測値を記録する"):
    measured_temp = st.number_input(
        "実測した路面温度（℃）",
        min_value=0.0,
        max_value=90.0,
        step=0.1,
        format="%.1f",
    )

    surface_type = st.selectbox(
        "測定した場所",
        ["アスファルト", "コンクリート", "芝生", "土", "その他"],
    )

    memo = st.text_input(
        "メモ",
        placeholder="例：直射日光、日陰、雨上がり など",
    )

    if st.button("実測値を確認"):
        display_diff = measured_temp - current_asphalt
        learning_diff = measured_temp - current_base_asphalt

        st.write(f"表示中の予測路面温度：{current_asphalt:.1f}℃")
        if round(current_base_asphalt, 1) != round(current_asphalt, 1):
            st.write(f"補正前の基準予測：{current_base_asphalt:.1f}℃")
        st.write(f"実測路面温度：{measured_temp:.1f}℃")
        st.write(f"表示予測との差分：{display_diff:+.1f}℃")
        if round(current_base_asphalt, 1) != round(current_asphalt, 1):
            st.write(f"補正前予測との差分：{learning_diff:+.1f}℃")

    if st.button("記録する"):
        diff = measured_temp - current_base_asphalt

        record = {
            "日時": pd.Timestamp.now(tz="Asia/Tokyo").tz_localize(None).strftime("%Y-%m-%d %H:%M"),
            "地点": location_name,
            "予測温度": round(current_base_asphalt, 1),
            "補正後予測温度": round(current_asphalt, 1),
            "実測温度": round(measured_temp, 1),
            "差分": round(diff, 1),
            "路面": surface_type,
            "メモ": memo,
            "データソース": MANUAL_SOURCE_LABEL,
            "気温": round(current_air, 1),
            "雲量": round(float(current["cloud_cover_pct"]), 1),
            "風速": round(float(current["wind_speed_kmh"]), 1),
            "降水量": round(float(current["precip_mm"]), 1),
            "日射": round(float(current["shortwave_radiation_wm2"]), 1),
            "昼フラグ": int(current["is_day"]),
        }

        try:
            if measurement_storage["backend"] == "google-sheets":
                append_measurement_to_google_sheet(
                    record,
                    measurement_storage["service_account_info"],
                    measurement_storage["spreadsheet_id"],
                    measurement_storage["worksheet_name"],
                )
            elif measurement_storage["backend"] == "apps-script":
                append_measurement_to_apps_script(
                    record,
                    measurement_storage["apps_script_url"],
                    measurement_storage["apps_script_token"],
                )
            else:
                append_measurement(record)
        except Exception:
            st.error("実測値の保存に失敗しました。保存先設定を確認してください。")
        else:
            st.session_state.measurement_saved = True
            st.rerun()

    history_df, history_label = summarize_measurements(measurement_history, location_name)
    if not history_df.empty:
        st.subheader("📋 実測履歴")

        history_asphalt_df = history_df[history_df["路面"] == "アスファルト"].dropna(subset=["差分"])
        history_display_diff = (
            history_asphalt_df["実測温度"]
            - history_asphalt_df["補正後予測温度"].fillna(history_asphalt_df["予測温度"])
        )
        metric_col1, metric_col2, metric_col3 = st.columns(3)
        metric_col1.metric("記録件数", f"{len(history_df)}件")

        if history_asphalt_df.empty:
            metric_col2.metric("補正前平均ずれ", "-")
            metric_col3.metric("表示予測平均ずれ", "-")
        else:
            metric_col2.metric("補正前平均ずれ", f"{history_asphalt_df['差分'].abs().mean():.1f}℃")
            metric_col3.metric("表示予測平均ずれ", f"{history_display_diff.abs().mean():.1f}℃")

        st.caption(history_label)

        display_history_df = history_df.copy()
        display_history_df["日時"] = display_history_df["日時"].dt.strftime("%Y-%m-%d %H:%M")
        display_history_df["表示差分"] = (
            display_history_df["実測温度"]
            - display_history_df["補正後予測温度"].fillna(display_history_df["予測温度"])
        ).round(1)
        display_history_df = display_history_df.rename(
            columns={
                "予測温度": "予測(補正前)",
                "補正後予測温度": "表示予測",
                "差分": "補正前差分",
                "データソース": "ソース",
            }
        )
        display_history_df = display_history_df[
            [
                "日時",
                "地点",
                "予測(補正前)",
                "表示予測",
                "実測温度",
                "補正前差分",
                "表示差分",
                "路面",
                "メモ",
                "ソース",
            ]
        ]
        st.dataframe(
            display_history_df,
            width="stretch"
        )

        csv_df = history_df.copy()
        csv_df["日時"] = csv_df["日時"].dt.strftime("%Y-%m-%d %H:%M")
        csv = csv_df.to_csv(
            index=False,
            encoding="utf-8-sig"
        ).encode("utf-8-sig")

        st.download_button(
            "📥 履歴CSVダウンロード",
            csv,
            file_name="wanwalk_measurements.csv",
            mime="text/csv",
        )

st.info(
    "この推定は実測値ではありません。特に夏場は、実際の路面を手で触るか赤外線温度計で確認してください。"
)
