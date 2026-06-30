from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from model import AsphaltModelConfig


MEASUREMENT_COLUMNS = [
    "日時",
    "地点",
    "予測温度",
    "補正後予測温度",
    "実測温度",
    "差分",
    "路面",
    "メモ",
    "データソース",
    "気温",
    "雲量",
    "風速",
    "降水量",
    "日射",
    "昼フラグ",
]
MEASUREMENT_FILE = Path("data") / "measurements.csv"
TEMPLE_MEASUREMENT_FILE = Path("temple.csv")
MIN_CALIBRATION_SAMPLES = 3
MIN_LINEAR_CALIBRATION_SAMPLES = 8
MIN_COEFFICIENT_REVIEW_SAMPLES = 8
IMPORTED_LOCATION_NAME = "取り込み実測"
MANUAL_SOURCE_LABEL = "手入力"
GOOGLE_SHEETS_SOURCE_LABEL = "Google Sheets"
DEFAULT_SHEET_WORKSHEET = "measurements"


@dataclass(frozen=True)
class CalibrationSummary:
    slope: float = 1.0
    intercept_c: float = 0.0
    sample_count: int = 0
    scope_label: str = ""
    mae_c: float = 0.0
    baseline_mae_c: float = 0.0
    method_label: str = "補正なし"
    imported_sample_count: int = 0
    manual_sample_count: int = 0

    @property
    def is_active(self) -> bool:
        return (
            self.sample_count >= MIN_CALIBRATION_SAMPLES
            and self.method_label != "補正なし"
        )

    @property
    def equation_text(self) -> str:
        if self.method_label == "固定補正":
            return f"予測値 {self.intercept_c:+.1f}℃"
        if self.method_label == "線形補正":
            return f"実測 ≒ {self.slope:.2f} × 予測 {self.intercept_c:+.1f}℃"
        return "補正なし"

    @property
    def improvement_c(self) -> float:
        return round(self.baseline_mae_c - self.mae_c, 1)


@dataclass(frozen=True)
class CoefficientReviewSummary:
    recommended_config: AsphaltModelConfig = field(default_factory=AsphaltModelConfig)
    sample_count: int = 0
    scope_label: str = ""
    baseline_mae_c: float = 0.0
    reviewed_mae_c: float = 0.0
    delta_solar_gain_c: float = 0.0
    delta_wind_cooling_factor: float = 0.0
    delta_rain_cooling_factor: float = 0.0
    delta_night_cooling_c: float = 0.0
    delta_safety_margin_c: float = 0.0

    @property
    def is_active(self) -> bool:
        return (
            self.sample_count >= MIN_COEFFICIENT_REVIEW_SAMPLES
            and self.reviewed_mae_c + 0.2 < self.baseline_mae_c
        )

    @property
    def improvement_c(self) -> float:
        return round(self.baseline_mae_c - self.reviewed_mae_c, 1)


@dataclass(frozen=True)
class MeasurementStorageStatus:
    backend: str
    label: str
    detail: str
    is_persistent: bool


def load_measurements(
    path: Path = MEASUREMENT_FILE,
    include_local: bool = True,
    extra_frames: list[pd.DataFrame] | None = None,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    if include_local:
        frames.append(_load_saved_measurements(path))
    if extra_frames:
        frames.extend(extra_frames)
    frames.append(load_temple_measurements())

    available_frames = [frame for frame in frames if not frame.empty]
    if not available_frames:
        return _empty_measurements_df()

    df = pd.concat(available_frames, ignore_index=True)
    df = _normalize_measurements(df)
    df = df.drop_duplicates().reset_index(drop=True)
    return df.sort_values("日時", ascending=False, na_position="last").reset_index(drop=True)


def append_measurement(record: dict[str, object], path: Path = MEASUREMENT_FILE) -> None:
    existing_df = _load_saved_measurements(path)
    new_df = _normalize_measurements(pd.DataFrame([record], columns=MEASUREMENT_COLUMNS))

    combined_df = pd.concat([new_df, existing_df], ignore_index=True)
    _save_measurements(combined_df, path)


def load_google_sheet_measurements(
    service_account_info: Mapping[str, Any],
    spreadsheet_id: str,
    worksheet_name: str = DEFAULT_SHEET_WORKSHEET,
) -> pd.DataFrame:
    worksheet = _open_google_worksheet(
        service_account_info,
        spreadsheet_id,
        worksheet_name,
        create_if_missing=False,
    )
    if worksheet is None:
        return _empty_measurements_df()

    values = worksheet.get_all_values()
    if not values:
        return _empty_measurements_df()

    headers = values[0]
    rows = values[1:]
    if not rows:
        return _empty_measurements_df()

    df = pd.DataFrame(rows, columns=headers)
    if "データソース" not in df.columns:
        df["データソース"] = GOOGLE_SHEETS_SOURCE_LABEL
    else:
        df["データソース"] = df["データソース"].replace("", GOOGLE_SHEETS_SOURCE_LABEL)
    return _normalize_measurements(df)


def append_measurement_to_google_sheet(
    record: dict[str, object],
    service_account_info: Mapping[str, Any],
    spreadsheet_id: str,
    worksheet_name: str = DEFAULT_SHEET_WORKSHEET,
) -> None:
    worksheet = _open_google_worksheet(
        service_account_info,
        spreadsheet_id,
        worksheet_name,
        create_if_missing=True,
    )
    _ensure_google_sheet_header(worksheet)

    normalized_df = _normalize_measurements(pd.DataFrame([record], columns=MEASUREMENT_COLUMNS))
    export_record = _export_measurements(normalized_df).iloc[0].fillna("")
    row_values = [export_record.get(column, "") for column in MEASUREMENT_COLUMNS]
    worksheet.append_row(row_values, value_input_option="USER_ENTERED")


def get_measurement_storage_status(
    backend: str,
    spreadsheet_id: str | None = None,
    worksheet_name: str = DEFAULT_SHEET_WORKSHEET,
) -> MeasurementStorageStatus:
    if backend == "google-sheets":
        return MeasurementStorageStatus(
            backend=backend,
            label="Google Sheets",
            detail=f"Spreadsheet: {spreadsheet_id} / Worksheet: {worksheet_name}",
            is_persistent=True,
        )

    return MeasurementStorageStatus(
        backend="local-csv",
        label="ローカルCSV",
        detail="data/measurements.csv に保存",
        is_persistent=False,
    )


def load_temple_measurements(path: Path = TEMPLE_MEASUREMENT_FILE) -> pd.DataFrame:
    if not path.exists():
        return _empty_measurements_df()

    header_df = pd.read_csv(path, header=None, nrows=2, dtype=str).fillna("")
    surface_hint = " ".join(
        value.strip()
        for value in header_df.iloc[1].tolist()
        if isinstance(value, str) and value.strip()
    )

    raw_df = pd.read_csv(
        path,
        skiprows=2,
        header=None,
        names=["raw_time", "予測温度", "実測温度", "天気"],
        dtype=str,
    )
    raw_df = raw_df.replace(r"^\s*$", pd.NA, regex=True)
    raw_df = raw_df.dropna(subset=["raw_time"])
    if raw_df.empty:
        return _empty_measurements_df()

    year = pd.Timestamp.fromtimestamp(path.stat().st_mtime).year
    raw_df["日時"] = pd.to_datetime(
        raw_df["raw_time"].map(
            lambda value: f"{year}/{value}" if pd.notna(value) else pd.NA
        ),
        format="%Y/%m/%d/%H:%M",
        errors="coerce",
    )

    normalized_df = pd.DataFrame(
        {
            "日時": raw_df["日時"],
            "地点": IMPORTED_LOCATION_NAME,
            "予測温度": pd.to_numeric(raw_df["予測温度"], errors="coerce"),
            "補正後予測温度": pd.to_numeric(raw_df["予測温度"], errors="coerce"),
            "実測温度": pd.to_numeric(raw_df["実測温度"], errors="coerce"),
            "路面": _extract_surface_type(surface_hint),
            "メモ": [
                _build_import_memo(surface_hint, weather_note)
                for weather_note in raw_df["天気"].fillna("")
            ],
            "データソース": path.name,
        }
    )
    normalized_df["差分"] = normalized_df["実測温度"] - normalized_df["予測温度"]
    normalized_df = normalized_df.dropna(subset=["日時", "予測温度", "実測温度"])

    return _normalize_measurements(normalized_df)


def build_calibration_summary(
    measurements_df: pd.DataFrame,
    location_name: str,
    min_samples: int = MIN_CALIBRATION_SAMPLES,
) -> CalibrationSummary:
    if measurements_df.empty:
        return CalibrationSummary()

    asphalt_df = measurements_df[measurements_df["路面"] == "アスファルト"].copy()
    asphalt_df = asphalt_df.dropna(subset=["予測温度", "実測温度"])
    if asphalt_df.empty:
        return CalibrationSummary()

    location_df = asphalt_df[asphalt_df["地点"] == location_name]

    if len(location_df) >= MIN_LINEAR_CALIBRATION_SAMPLES:
        scope_df = location_df
        scope_label = f"{location_name}のアスファルト実測"
    elif len(asphalt_df) >= min_samples:
        if len(location_df) == len(asphalt_df) and len(location_df) >= min_samples:
            scope_df = location_df
            scope_label = f"{location_name}のアスファルト実測"
        else:
            scope_df = asphalt_df
            scope_label = "全地点のアスファルト実測"
    elif len(location_df) >= min_samples:
        scope_df = location_df
        scope_label = f"{location_name}のアスファルト実測"
    else:
        return CalibrationSummary()

    baseline_mae_c = float((scope_df["実測温度"] - scope_df["予測温度"]).abs().mean())
    source_series = scope_df["データソース"].fillna("")
    manual_sample_count = int(source_series.eq(MANUAL_SOURCE_LABEL).sum())
    imported_sample_count = int(source_series.eq(TEMPLE_MEASUREMENT_FILE.name).sum())

    candidates: list[tuple[str, float, float, float]] = [
        ("補正なし", 1.0, 0.0, baseline_mae_c),
    ]

    offset_c = float(np.clip((scope_df["実測温度"] - scope_df["予測温度"]).median(), -8.0, 8.0))
    offset_mae_c = float(
        (scope_df["実測温度"] - (scope_df["予測温度"] + offset_c)).abs().mean()
    )
    candidates.append(("固定補正", 1.0, round(offset_c, 1), offset_mae_c))

    if (
        len(scope_df) >= MIN_LINEAR_CALIBRATION_SAMPLES
        and scope_df["予測温度"].nunique() >= 3
    ):
        slope, intercept_c = np.polyfit(scope_df["予測温度"], scope_df["実測温度"], 1)
        slope = float(np.clip(slope, 0.7, 1.4))
        intercept_c = float(np.clip(intercept_c, -12.0, 12.0))
        linear_mae_c = float(
            (scope_df["実測温度"] - (scope_df["予測温度"] * slope + intercept_c)).abs().mean()
        )
        candidates.append(("線形補正", slope, intercept_c, linear_mae_c))

    method_label, slope, intercept_c, mae_c = min(candidates, key=lambda item: item[3])

    return CalibrationSummary(
        slope=round(slope, 3),
        intercept_c=round(intercept_c, 1),
        sample_count=len(scope_df),
        scope_label=scope_label,
        baseline_mae_c=round(baseline_mae_c, 1),
        mae_c=round(mae_c, 1),
        method_label=method_label,
        imported_sample_count=imported_sample_count,
        manual_sample_count=manual_sample_count,
    )


def build_coefficient_review(
    measurements_df: pd.DataFrame,
    location_name: str,
    base_config: AsphaltModelConfig | None = None,
) -> CoefficientReviewSummary:
    cfg = base_config or AsphaltModelConfig()
    if measurements_df.empty:
        return CoefficientReviewSummary(recommended_config=cfg)

    manual_df = measurements_df[
        (measurements_df["路面"] == "アスファルト")
        & (measurements_df["データソース"] == MANUAL_SOURCE_LABEL)
    ].copy()
    required_columns = [
        "予測温度",
        "実測温度",
        "風速",
        "降水量",
        "日射",
        "昼フラグ",
    ]
    manual_df = manual_df.dropna(subset=required_columns)
    if manual_df.empty:
        return CoefficientReviewSummary(recommended_config=cfg)

    location_df = manual_df[manual_df["地点"] == location_name].copy()
    if len(location_df) >= MIN_COEFFICIENT_REVIEW_SAMPLES:
        scope_df = location_df
        scope_label = f"{location_name}の手入力実測"
    elif len(manual_df) >= MIN_COEFFICIENT_REVIEW_SAMPLES:
        scope_df = manual_df
        scope_label = "全地点の手入力実測"
    else:
        return CoefficientReviewSummary(
            recommended_config=cfg,
            sample_count=len(location_df) if not location_df.empty else len(manual_df),
            scope_label=f"{location_name}の手入力実測" if not location_df.empty else "全地点の手入力実測",
            baseline_mae_c=round(float((manual_df["実測温度"] - manual_df["予測温度"]).abs().mean()), 1),
            reviewed_mae_c=round(float((manual_df["実測温度"] - manual_df["予測温度"]).abs().mean()), 1),
        )

    baseline_residual = scope_df["実測温度"] - scope_df["予測温度"]
    radiation_factor = np.clip(scope_df["日射"].astype(float) / 800.0, 0.0, 1.0)
    wind_term = -scope_df["風速"].astype(float)
    rain_term = -scope_df["降水量"].astype(float)
    night_term = -(1 - scope_df["昼フラグ"].astype(float).clip(0.0, 1.0))
    bias_term = np.ones(len(scope_df))

    design_matrix = np.column_stack(
        [
            radiation_factor.to_numpy(),
            wind_term.to_numpy(),
            rain_term.to_numpy(),
            night_term.to_numpy(),
            bias_term,
        ]
    )
    target = baseline_residual.to_numpy(dtype=float)

    deltas, *_ = np.linalg.lstsq(design_matrix, target, rcond=None)
    delta_solar, delta_wind, delta_rain, delta_night, delta_margin = [
        float(value) for value in deltas
    ]

    delta_solar = float(np.clip(delta_solar, -8.0, 8.0))
    delta_wind = float(np.clip(delta_wind, -0.12, 0.12))
    delta_rain = float(np.clip(delta_rain, -2.5, 2.5))
    delta_night = float(np.clip(delta_night, -2.0, 2.0))
    delta_margin = float(np.clip(delta_margin, -4.0, 4.0))

    adjusted_prediction = scope_df["予測温度"] + (
        radiation_factor * delta_solar
        + wind_term * delta_wind
        + rain_term * delta_rain
        + night_term * delta_night
        + delta_margin
    )

    recommended_config = AsphaltModelConfig(
        max_solar_gain_c=float(np.clip(cfg.max_solar_gain_c + delta_solar, 12.0, 36.0)),
        wind_cooling_factor=float(np.clip(cfg.wind_cooling_factor + delta_wind, 0.05, 0.45)),
        rain_cooling_factor=float(np.clip(cfg.rain_cooling_factor + delta_rain, 0.5, 8.0)),
        night_cooling_c=float(np.clip(cfg.night_cooling_c + delta_night, 0.0, 6.0)),
        heat_memory=cfg.heat_memory,
        safety_margin_c=float(np.clip(cfg.safety_margin_c + delta_margin, -1.0, 8.0)),
    )

    baseline_mae_c = float(baseline_residual.abs().mean())
    reviewed_mae_c = float((scope_df["実測温度"] - adjusted_prediction).abs().mean())

    return CoefficientReviewSummary(
        recommended_config=recommended_config,
        sample_count=len(scope_df),
        scope_label=scope_label,
        baseline_mae_c=round(baseline_mae_c, 1),
        reviewed_mae_c=round(reviewed_mae_c, 1),
        delta_solar_gain_c=round(delta_solar, 2),
        delta_wind_cooling_factor=round(delta_wind, 3),
        delta_rain_cooling_factor=round(delta_rain, 3),
        delta_night_cooling_c=round(delta_night, 2),
        delta_safety_margin_c=round(delta_margin, 2),
    )


def summarize_measurements(
    measurements_df: pd.DataFrame,
    location_name: str,
) -> tuple[pd.DataFrame, str]:
    if measurements_df.empty:
        return measurements_df, "履歴はまだありません"

    location_df = measurements_df[
        (measurements_df["地点"] == location_name)
        | (measurements_df["地点"] == IMPORTED_LOCATION_NAME)
    ].copy()
    if not location_df.empty:
        if (location_df["地点"] == IMPORTED_LOCATION_NAME).any():
            return location_df, f"{location_name}と取り込み実測の履歴"
        return location_df, f"{location_name}の履歴"

    return measurements_df.copy(), "全履歴"


def summarize_source_counts(measurements_df: pd.DataFrame) -> tuple[int, int]:
    if measurements_df.empty or "データソース" not in measurements_df.columns:
        return 0, 0

    source_series = measurements_df["データソース"].fillna("")
    imported_count = int(source_series.eq(TEMPLE_MEASUREMENT_FILE.name).sum())
    manual_count = int(source_series.eq(MANUAL_SOURCE_LABEL).sum())
    return imported_count, manual_count


def _empty_measurements_df() -> pd.DataFrame:
    return pd.DataFrame(columns=MEASUREMENT_COLUMNS)


def _load_saved_measurements(path: Path) -> pd.DataFrame:
    if not path.exists():
        return _empty_measurements_df()

    df = pd.read_csv(path, encoding="utf-8-sig")
    return _normalize_measurements(df)


def _normalize_measurements(df: pd.DataFrame) -> pd.DataFrame:
    normalized_df = df.copy()
    for column in MEASUREMENT_COLUMNS:
        if column not in normalized_df.columns:
            normalized_df[column] = pd.NA

    normalized_df = normalized_df[MEASUREMENT_COLUMNS].copy()
    if normalized_df.empty:
        return _empty_measurements_df()

    normalized_df["日時"] = pd.to_datetime(normalized_df["日時"], errors="coerce")
    for column in (
        "予測温度",
        "補正後予測温度",
        "実測温度",
        "差分",
        "気温",
        "雲量",
        "風速",
        "降水量",
        "日射",
        "昼フラグ",
    ):
        normalized_df[column] = pd.to_numeric(normalized_df[column], errors="coerce")

    return normalized_df


def _extract_surface_type(surface_hint: str) -> str:
    if "アスファルト" in surface_hint:
        return "アスファルト"
    if "コンクリート" in surface_hint:
        return "コンクリート"
    return "その他"


def _build_import_memo(surface_hint: str, weather_note: str) -> str:
    note_parts = []
    exposure_note = surface_hint.replace("アスファルト", "").strip()
    if exposure_note:
        note_parts.append(exposure_note)
    if weather_note:
        note_parts.append(str(weather_note).strip())
    return " / ".join(part for part in note_parts if part)


def _save_measurements(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    export_df = _export_measurements(_normalize_measurements(df))
    export_df.to_csv(path, index=False, encoding="utf-8-sig")


def _export_measurements(df: pd.DataFrame) -> pd.DataFrame:
    export_df = df.copy()
    if "日時" in export_df.columns:
        export_df["日時"] = pd.to_datetime(export_df["日時"], errors="coerce").dt.strftime("%Y-%m-%d %H:%M")
    return export_df


def _open_google_worksheet(
    service_account_info: Mapping[str, Any],
    spreadsheet_id: str,
    worksheet_name: str,
    create_if_missing: bool,
):
    import gspread
    from gspread.exceptions import WorksheetNotFound

    client = gspread.service_account_from_dict(dict(service_account_info))
    spreadsheet = client.open_by_key(spreadsheet_id)
    try:
        return spreadsheet.worksheet(worksheet_name)
    except WorksheetNotFound:
        if not create_if_missing:
            return None
        return spreadsheet.add_worksheet(title=worksheet_name, rows=2000, cols=max(26, len(MEASUREMENT_COLUMNS)))


def _ensure_google_sheet_header(worksheet) -> None:
    header_values = worksheet.row_values(1)
    if header_values == MEASUREMENT_COLUMNS:
        return

    worksheet.update("A1", [MEASUREMENT_COLUMNS])
