from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
import requests


@dataclass(frozen=True)
class WeatherRequest:
    """Open-Meteo API に渡す地点情報。"""

    latitude: float
    longitude: float
    forecast_days: int = 2
    timezone: str = "Asia/Tokyo"


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
    "User-Agent": "WanWalk/1.0"
    }

    response = requests.get(
        url,
        params=params,
        headers=headers,
        timeout=20,
    )

    print(response.status_code)
    print(response.text[:300])

    response = requests.get(url, params=params, timeout=20)
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
