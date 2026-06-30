from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import pandas as pd
import requests


WEATHER_CACHE_DIR = Path("data") / "weather_cache"
MAX_WEATHER_CACHE_AGE_MINUTES = 60


@dataclass(frozen=True)
class WeatherRequest:
    """Open-Meteo API に渡す地点情報。"""

    latitude: float
    longitude: float
    forecast_days: int = 2
    timezone: str = "Asia/Tokyo"


@dataclass(frozen=True)
class WeatherFetchResult:
    weather_df: pd.DataFrame
    fetched_at: pd.Timestamp
    source: str
    age_minutes: float
    is_stale_fallback: bool = False


def fetch_hourly_weather(req: WeatherRequest) -> pd.DataFrame:
    """
    Open-Meteo の無料APIから時間別予報を取得する。

    取得する主な値:
    - 気温
    - 相対湿度
    - 降水量
    - 雲量
    - 風速
    - 日中/夜間フラグ

    Returns:
        pandas.DataFrame
    """
    url = "https://api.open-meteo.com/v1/forecast"
    params: dict[str, Any] = {
        "latitude": req.latitude,
        "longitude": req.longitude,
        "forecast_days": req.forecast_days,
        "timezone": req.timezone,
        "hourly": ",".join(
            [
                "temperature_2m",
                "relative_humidity_2m",
                "precipitation",
                "cloud_cover",
                "wind_speed_10m",
                "is_day",
                "shortwave_radiation",
            ]
        ),
    }

    headers = {
        "User-Agent": "WanWalk/1.0",
    }

    response = requests.get(
        url,
        params=params,
        headers=headers,
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()

    hourly = data["hourly"]
    df = pd.DataFrame(hourly)
    df["time"] = pd.to_datetime(df["time"])
    df = df.rename(
        columns={
            "temperature_2m": "air_temp_c",
            "relative_humidity_2m": "humidity_pct",
            "precipitation": "precip_mm",
            "cloud_cover": "cloud_cover_pct",
            "wind_speed_10m": "wind_speed_kmh",
            "is_day": "is_day",
            "shortwave_radiation": "shortwave_radiation_wm2",
        }
    )
    return df


def get_hourly_weather(
    req: WeatherRequest,
    max_cache_age_minutes: int = MAX_WEATHER_CACHE_AGE_MINUTES,
) -> WeatherFetchResult:
    now = pd.Timestamp.now(tz=req.timezone)
    cached_result = _load_cached_weather(req, now)

    if cached_result and cached_result.age_minutes < max_cache_age_minutes:
        return cached_result

    try:
        weather_df = fetch_hourly_weather(req)
    except Exception:
        if cached_result:
            return WeatherFetchResult(
                weather_df=cached_result.weather_df,
                fetched_at=cached_result.fetched_at,
                source="stale-cache",
                age_minutes=round(cached_result.age_minutes, 1),
                is_stale_fallback=True,
            )
        raise

    fetched_at = now
    _save_cached_weather(req, weather_df, fetched_at)
    return WeatherFetchResult(
        weather_df=weather_df,
        fetched_at=fetched_at,
        source="api",
        age_minutes=0.0,
        is_stale_fallback=False,
    )


def _load_cached_weather(
    req: WeatherRequest,
    now: pd.Timestamp,
) -> WeatherFetchResult | None:
    csv_path, meta_path = _cache_paths(req)
    if not csv_path.exists() or not meta_path.exists():
        return None

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        fetched_at = pd.Timestamp(meta["fetched_at"])
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.tz_localize(req.timezone)
        else:
            fetched_at = fetched_at.tz_convert(req.timezone)
        weather_df = pd.read_csv(csv_path)
        weather_df["time"] = pd.to_datetime(weather_df["time"])
    except Exception:
        return None

    age_minutes = max(0.0, (now - fetched_at).total_seconds() / 60.0)
    return WeatherFetchResult(
        weather_df=weather_df,
        fetched_at=fetched_at,
        source="cache",
        age_minutes=round(age_minutes, 1),
        is_stale_fallback=False,
    )


def _save_cached_weather(
    req: WeatherRequest,
    weather_df: pd.DataFrame,
    fetched_at: pd.Timestamp,
) -> None:
    csv_path, meta_path = _cache_paths(req)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    weather_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    meta = {
        "fetched_at": fetched_at.isoformat(),
        "latitude": req.latitude,
        "longitude": req.longitude,
        "forecast_days": req.forecast_days,
        "timezone": req.timezone,
    }
    meta_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _cache_paths(req: WeatherRequest) -> tuple[Path, Path]:
    cache_key = (
        f"{req.latitude:.4f}_{req.longitude:.4f}_{req.forecast_days}_{req.timezone}"
        .replace(".", "_")
        .replace(":", "_")
        .replace("/", "_")
    )
    csv_path = WEATHER_CACHE_DIR / f"{cache_key}.csv"
    meta_path = WEATHER_CACHE_DIR / f"{cache_key}.json"
    return csv_path, meta_path
