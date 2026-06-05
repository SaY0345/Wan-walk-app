from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class AsphaltModelConfig:
    """
    アスファルト温度推定モデルの係数。

    これは物理モデルではなく、犬の散歩判断向けの安全寄り簡易モデル。
    実測値を集めたら、ここを調整する。
    """

    # 晴天・日中・昼前後の最大日射上乗せ温度
    max_solar_gain_c: float = 24.0

    # 風による冷却係数。風速 km/h に対して引く。
    wind_cooling_factor: float = 0.22

    # 雨による冷却係数。降水量 mm/h に対して引く。
    rain_cooling_factor: float = 4.0

    # 夜間の放射冷却。夜は路面が気温より少し下がる方向にする。
    night_cooling_c: float = 2.0

    # 蓄熱の残りやすさ。大きいほど路面温度の変化が遅れる。
    heat_memory: float = 0.62

    # 安全寄りに上乗せするマージン。
    safety_margin_c: float = 2.0


def _solar_gain(hour: int, is_day: int, cloud_cover_pct: float, precip_mm: float,max_gain: float) -> float:
    """
    時刻・日中フラグ・雲量から日射補正を計算する。

    12〜13時ごろをピークにした簡易カーブ。
    雲量が多いほど日射補正を下げる。
    """
    if not is_day:
        return 0.0

    # 5時〜19時程度を日射時間帯として、13時ピークの山にする
    # sin カーブで自然に上げ下げする
    daylight_start = 5
    daylight_end = 19
    if hour < daylight_start or hour > daylight_end:
        return 0.0

    x = (hour - daylight_start) / (daylight_end - daylight_start)
    time_factor = max(0.0, np.sin(np.pi * x))

    # 雲量100%でも日射を完全ゼロにはしない
    cloud_factor = 1.0 - (cloud_cover_pct / 100.0) * 0.95
    cloud_factor = min(max(cloud_factor, 0.05), 1.0)
    
    # 雨が降るほど日射を抑制
    rain_factor = max(0.0, 1.0 - precip_mm / 5.0)
    
    return max_gain * time_factor * cloud_factor * rain_factor

def _solar_gain_from_radiation(shortwave_radiation_wm2: float, max_gain: float) -> float:
    radiation = max(0.0, float(shortwave_radiation_wm2))

    # 800W/m²くらいを強い日射の目安として、0〜1に正規化
    radiation_factor = min(radiation / 800.0, 1.0)

    return max_gain * radiation_factor

def estimate_asphalt_temperature(
    weather_df: pd.DataFrame,
    config: AsphaltModelConfig | None = None,
) -> pd.DataFrame:
    """
    時間別気象データから推定アスファルト温度を計算する。

    Args:
        weather_df: fetch_hourly_weather() の戻り値
        config: 係数設定

    Returns:
        元データに asphalt_temp_c, risk_level, walk_judgement を追加した DataFrame
    """
    cfg = config or AsphaltModelConfig()
    df = weather_df.copy()

    raw_estimates: list[float] = []

    for _, row in df.iterrows():
        hour = int(row["time"].hour)
        air = float(row["air_temp_c"])
        cloud = float(row["cloud_cover_pct"])
        wind = float(row["wind_speed_kmh"])
        rain = float(row["precip_mm"])
        is_day = int(row["is_day"])

        solar = _solar_gain_from_radiation(row["shortwave_radiation_wm2"], cfg.max_solar_gain_c,)
        wind_cooling = min(wind * cfg.wind_cooling_factor, 6.0)
        rain_cooling = min(rain * cfg.rain_cooling_factor, 8.0)
        night_cooling = 0.0 if is_day else cfg.night_cooling_c

        raw = air + solar - wind_cooling - rain_cooling - night_cooling + cfg.safety_margin_c
        
        min_offset = 4.0 if not is_day else 2.0
        raw = max(raw, air - min_offset)
        
        raw_estimates.append(raw)

    # 蓄熱補正:
    # 路面温度は気温や日射の変化に即時追従しないため、前時刻の値を混ぜる。
    smoothed: list[float] = []
    for i, raw in enumerate(raw_estimates):
        if i == 0:
            smoothed.append(raw)
        else:
            previous = smoothed[-1]
            smoothed.append(cfg.heat_memory * previous + (1 - cfg.heat_memory) * raw)

    df["asphalt_temp_c"] = np.round(smoothed, 1)
    df["risk_level"] = df["asphalt_temp_c"].apply(classify_risk)
    df["walk_judgement"] = df["asphalt_temp_c"].apply(walk_judgement)

    return df


def classify_risk(temp_c: float) -> str:
    if temp_c < 30:
        return "安全"
    if temp_c < 40:
        return "注意"
    if temp_c < 55:
        return "危険"
    return "非常に危険"


def walk_judgement(temp_c: float) -> str:
    if temp_c < 30:
        return "散歩しやすい"
    if temp_c < 40:
        return "短時間・日陰中心"
    if temp_c < 55:
        return "肉球リスク高め"
    return "原則避ける"


def find_recommended_windows(df: pd.DataFrame, max_temp_c: float = 30.0) -> list[str]:
    """
    推定アスファルト温度が指定値以下の連続時間帯を抽出する。
    """
    safe = df[df["asphalt_temp_c"] <= max_temp_c].copy()
    if safe.empty:
        return []

    windows: list[str] = []
    start = None
    prev = None

    for t in safe["time"]:
        if start is None:
            start = t
            prev = t
            continue

        # 1時間連続していなければ区切る
        if (t - prev).total_seconds() > 3600 * 1.5:
            if start.date() == prev.date():
                windows.append(f"{start:%m/%d %H:%M}〜{prev:%H:%M}")
            else:
                windows.append(f"{start:%m/%d %H:%M}〜{prev:%m/%d %H:%M}")
            start = t

        prev = t

    if start is not None and prev is not None:
        if start.date() == prev.date():
            windows.append(f"{start:%m/%d %H:%M}〜{prev:%H:%M}")
        else:
            windows.append(f"{start:%m/%d %H:%M}〜{prev:%m/%d %H:%M}")

    return windows
