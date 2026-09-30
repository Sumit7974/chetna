"""M1 Day 3: Deterministic Proxy Dataset Generator and Hotspot Calibration.

Builds leakage-free training datasets for multi-horizon (+1h, +3h, +6h) flood-risk modeling
using historical rainfall events, documented chronic hotspots, and static terrain vulnerability.

IMPORTANT PROVENANCE NOTE:
All generated labels in this dataset are PROXY LABELS derived through deterministic
calibration of historical rainfall against documented municipal hotspot trigger thresholds
and static terrain vulnerability. They are NOT real-world physical water-depth sensor logs
or field observations. Provenance metadata is strictly preserved on every record.
"""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

from src.static_risk.hotspots import (
    DEFAULT_HOTSPOT_CELL_MAPPING,
    DEFAULT_M1_DATA_DIR,
    Hotspot,
    load_backtest_events,
    load_historical_rainfall,
    load_hotspots,
)

logger = logging.getLogger(__name__)

# Feature column order for ML models (clean feature policy)
# Strictly excludes target variables and target-derived formulas (trigger_rain_threshold, flood_risk_proxy)
FEATURE_COLUMNS = [
    "rainfall_mm",
    "rain_past_24h",
    "elevation",
    "slope",
    "flow_accumulation",
    "imperviousness",
    "vulnerability_score",
    "is_hotspot",
]

FORBIDDEN_FEATURE_COLUMNS = {
    "waterlogged_proxy",
    "flood_risk_proxy",
    "proxy_risk_tier",
    "inundation_depth_proxy_m",
    "trigger_rain_threshold",
}

# Programmatic assertion against target formulation leakage
assert not set(FEATURE_COLUMNS).intersection(FORBIDDEN_FEATURE_COLUMNS), (
    "Target or target-derived columns detected in FEATURE_COLUMNS policy!"
)

DEFAULT_PROVENANCE_STRING = (
    "Proxy/Synthetic Development Observation (Calibrated to GCC Chronic Hotspot "
    "Trigger Thresholds and M1 Day 2 Static Terrain Vulnerability)"
)


@dataclass
class ProxySample:
    """Single sample representing a cell state at time t for a specific forecast horizon.

    Includes dynamic weather features, static terrain/drainage features, calibrated proxy targets,
    and provenance metadata.
    """
    sample_id: str
    event_id: str
    cell_id: str
    hotspot_id: Optional[str]
    timestamp: str
    horizon: int
    rainfall_mm: float
    rain_past_24h: float
    elevation: float
    slope: float
    flow_accumulation: float
    imperviousness: float
    vulnerability_score: float
    trigger_rain_threshold: float
    is_hotspot: float
    waterlogged_proxy: int
    flood_risk_proxy: float
    proxy_risk_tier: str
    is_proxy: bool = True
    data_source: str = DEFAULT_PROVENANCE_STRING

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_feature_vector(self) -> List[float]:
        return [
            float(self.rainfall_mm),
            float(self.rain_past_24h),
            float(self.elevation),
            float(self.slope),
            float(self.flow_accumulation),
            float(self.imperviousness),
            float(self.vulnerability_score),
            float(self.is_hotspot),
        ]


def calibrate_hotspot_threshold(
    base_trigger_mm: float,
    vulnerability_score: float,
    rain_past_24h: float = 0.0,
) -> float:
    """Deterministically calibrates the effective rainfall trigger threshold for a cell.

    Physical hydrologic rationale:
    1. Base trigger: GCC chronic hotspot documented 1h or 6h rain trigger (e.g. 15-35 mm for 1h).
    2. Vulnerability adjustment: Cells with higher static vulnerability (low elevation, high imperviousness,
       basin topography) saturate and back up faster:
           factor_vuln = 1.35 - 0.70 * vulnerability_score
           - High vuln (0.90) -> factor ~0.72 (trigger rain reduced by ~28%)
           - Moderate vuln (0.50) -> factor ~1.00 (trigger rain unchanged)
           - Low vuln (0.15) -> factor ~1.25 (trigger rain increased by ~25%)
    3. Antecedent soil moisture: Saturated ground (rain_past_24h >= 35.0 mm) reduces infiltration,
       lowering effective threshold by an additional 15%.

    Returns:
        Effective rainfall threshold in mm (strictly positive).
    """
    v = max(0.0, min(1.0, float(vulnerability_score)))
    vuln_factor = 1.35 - (0.70 * v)
    threshold = base_trigger_mm * vuln_factor

    if rain_past_24h >= 35.0:
        threshold *= 0.85
    elif rain_past_24h >= 20.0:
        threshold *= 0.92

    return max(5.0, round(threshold, 2))


def compute_proxy_target(
    rainfall_mm: float,
    effective_threshold: float,
    vulnerability_score: float,
) -> Tuple[int, float, str]:
    """Computes binary waterlogged proxy and continuous flood risk proxy score.

    Args:
        rainfall_mm: Forecast rainfall accumulation for the horizon.
        effective_threshold: Calibrated critical rainfall threshold in mm.
        vulnerability_score: Static terrain vulnerability in [0, 1].

    Returns:
        Tuple of (waterlogged_proxy (0 or 1), flood_risk_proxy in [0, 1], proxy_risk_tier).
    """
    r = max(0.0, float(rainfall_mm))
    thresh = max(1.0, float(effective_threshold))
    v = max(0.0, min(1.0, float(vulnerability_score)))

    # Continuous proxy risk score combining rainfall demand/capacity ratio (65%) and static vulnerability (35%)
    rain_ratio = min(1.0, r / thresh)
    score = round(0.65 * rain_ratio + 0.35 * v, 4)
    score = max(0.0, min(1.0, score))

    # Binary proxy label
    is_waterlogged = 1 if (r >= thresh or score >= 0.70) else 0

    # Risk level classification
    if score >= 0.70:
        tier = "High"
    elif score >= 0.40:
        tier = "Medium"
    else:
        tier = "Low"

    return is_waterlogged, score, tier


def compute_patna_event_target(
    event_id: str,
    cell_id: str,
    timestamp: str,
    vulnerability_score: float,
    rainfall_mm: float,
    effective_threshold: float,
) -> Tuple[int, float, str, str]:
    """Computes target label and risk score for Patna historical events.

    CRITICAL EVALUATION INTEGRITY RULE:
    The target label (waterlogged_proxy) is derived strictly from independently documented
    municipal flood inundation occurrences and active event impact windows (PMC / BSDMA / IMD records).
    It is NOT computed from `rainfall_mm >= effective_threshold` to prevent feature leakage.
    Rainfall is purely an input feature.

    Returns:
        Tuple of (waterlogged_proxy, flood_risk_proxy, proxy_risk_tier, provenance_string).
    """
    v = max(0.0, min(1.0, float(vulnerability_score)))
    rf = max(0.0, float(rainfall_mm))
    thresh = max(1.0, float(effective_threshold))
    rf_ratio = min(1.0, rf / thresh)

    if event_id == "EVT_PATNA_2019_FLOOD":
        # PMC & BSDMA documented catastrophic inundation across the 10 chronic saucer depressions:
        # Rajendra Nagar, Kankarbagh, Saidpur, Boring Road, Bailey Road, Gandhi Maidan,
        # Patliputra Colony, Anisabad, Digha, Bazar Samiti.
        # Major sump failure occurred starting 2019-09-28T00:00 through 2019-09-30T23:00.
        patna_chronic_hotspot_cells = {
            "CELL_RAJ_01", "CELL_KAN_01", "CELL_SAI_01", "CELL_BOR_01",
            "CELL_BAI_01", "CELL_GAN_01", "CELL_PAT_01", "CELL_ANI_01",
            "CELL_DIG_01", "CELL_BAZ_01"
        }
        is_inundation_window = timestamp >= "2019-09-28T00:00"
        if cell_id in patna_chronic_hotspot_cells and is_inundation_window:
            wl = 1
            score = round(min(1.0, 0.70 + 0.25 * v), 4)
            tier = "High"
            source = "Proxy Observation (Calibrated to Patna Documented Inundation Occurrence and Copernicus DEM)"
        else:
            wl = 0
            score = round(max(0.0, min(0.68, 0.20 * v + 0.30 * rf_ratio)), 4)
            tier = "Medium" if score >= 0.40 else "Low"
            source = "Proxy Observation (Calibrated to Patna Documented Non-Inundated Area and Copernicus DEM)"

    elif event_id == "EVT_PATNA_2024_09_HEAVY_RAIN":
        # IMD Meteorological Centre Patna special study & PMC logs:
        # Documented localized urban waterlogging occurred in Patna's chronic lowest sump depressions:
        # Rajendra Nagar (CELL_RAJ_01), Kankarbagh (CELL_KAN_01), Saidpur (CELL_SAI_01).
        # Documented peak inundation window: 2024-09-28T12:00 to 2024-09-29T12:00.
        patna_2024_inundated_cells = {"CELL_RAJ_01", "CELL_KAN_01", "CELL_SAI_01"}
        is_inundation_window = "2024-09-28T12:00" <= timestamp <= "2024-09-29T12:00"
        if cell_id in patna_2024_inundated_cells and is_inundation_window:
            wl = 1
            score = round(min(1.0, 0.72 + 0.25 * v), 4)
            tier = "High"
            source = "Proxy Observation (Calibrated to Patna Documented Localized Inundation and PMC Logs)"
        else:
            wl = 0
            score = round(max(0.0, min(0.68, 0.15 * v + 0.35 * rf_ratio)), 4)
            tier = "Medium" if score >= 0.40 else "Low"
            source = "Proxy Observation (Calibrated to Patna Documented Non-Inundated Area and PMC Logs)"
    else:
        wl, score, tier = compute_proxy_target(rainfall_mm=rf, effective_threshold=thresh, vulnerability_score=v)
        source = DEFAULT_PROVENANCE_STRING

    return wl, score, tier, source


def load_static_cell_catalog(
    static_risk_path: Optional[Union[str, Path]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Loads static terrain and vulnerability attributes for all available cells."""
    path = Path(static_risk_path) if static_risk_path else DEFAULT_M1_DATA_DIR / "static_risk_scores.json"
    if not path.is_file():
        logger.warning("Static risk file not found at %s. Returning empty catalog.", path)
        return {}

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    cells = data.get("cells", []) if isinstance(data, dict) else data
    catalog: Dict[str, Dict[str, Any]] = {}
    for c in cells:
        cid = c.get("cell_id")
        if not cid:
            continue
        raw = c.get("raw_features", {})
        catalog[cid] = {
            "cell_id": cid,
            "vulnerability_score": float(c.get("vulnerability_score", 0.50)),
            "elevation": float(raw.get("elevation", 10.0)),
            "slope": float(raw.get("slope", 1.0)),
            "flow_accumulation": float(raw.get("flow_accumulation", 1000.0)),
            "imperviousness": float(raw.get("imperviousness", 0.60)),
        }
    return catalog


def build_proxy_training_dataset(
    data_dir: Optional[Union[str, Path]] = None,
    static_risk_file: Optional[Union[str, Path]] = None,
    output_dir: Optional[Union[str, Path]] = None,
    horizons: Sequence[int] = (1, 3, 6),
) -> List[ProxySample]:
    """Deterministically generates a multi-horizon proxy training dataset for M1 Day 3.

    Integrates:
    - 10 GCC chronic hotspots with documented trigger rainfall thresholds
    - Historical heavy rainfall series (Michaung 2023, Nov 2021)
    - Static terrain vulnerability scores from M1 Day 2
    - Horizons +1h, +3h, +6h without temporal leakage

    Returns:
        List of ProxySample instances.
    """
    directory = Path(data_dir) if data_dir else DEFAULT_M1_DATA_DIR
    hotspots = load_hotspots(directory / "hotspots.json" if (directory / "hotspots.json").exists() else None)
    events = load_backtest_events(directory / "backtest_events.json" if (directory / "backtest_events.json").exists() else None)
    static_catalog = load_static_cell_catalog(static_risk_file or directory / "static_risk_scores.json")

    hotspot_by_cell: Dict[str, Hotspot] = {}
    for h in hotspots:
        cid = h.cell_id or DEFAULT_HOTSPOT_CELL_MAPPING.get(h.hotspot_id)
        if cid:
            hotspot_by_cell[cid] = h

    # If static catalog is available, combine hotspot cells and other grid cells
    cell_ids = list(static_catalog.keys())
    if not cell_ids:
        # Fall back to hotspot mapped cells
        cell_ids = [h.cell_id or DEFAULT_HOTSPOT_CELL_MAPPING.get(h.hotspot_id) for h in hotspots if (h.cell_id or DEFAULT_HOTSPOT_CELL_MAPPING.get(h.hotspot_id))]

    samples: List[ProxySample] = []

    for event in events:
        series = load_historical_rainfall(event.rainfall_data_file, data_dir=directory)
        timestamps = [r.timestamp for r in series.records]
        values = [r.rain_mm for r in series.records]
        n_times = len(timestamps)

        for i, ts in enumerate(timestamps):
            # Compute antecedent 24-hour rainfall (strictly preceding time t)
            past_start = max(0, i - 24)
            rain_past_24h = round(sum(values[past_start:i]), 2)

            # Cumulative forward rainfall for each horizon
            r1h = round(sum(values[i : min(n_times, i + 1)]), 2)
            r3h = round(sum(values[i : min(n_times, i + 3)]), 2)
            r6h = round(sum(values[i : min(n_times, i + 6)]), 2)
            horizon_rain = {1: r1h, 3: r3h, 6: r6h}

            for cid in cell_ids:
                if not cid:
                    continue

                cell_static = static_catalog.get(cid, {})
                v_score = cell_static.get("vulnerability_score", 0.50)
                elev = cell_static.get("elevation", 10.0)
                slp = cell_static.get("slope", 1.0)
                flow_acc = cell_static.get("flow_accumulation", 1000.0)
                imp = cell_static.get("imperviousness", 0.60)

                h_info = hotspot_by_cell.get(cid)
                is_hotspot = 1.0 if h_info else 0.0
                hid = h_info.hotspot_id if h_info else None

                if h_info:
                    base_trig_1h = h_info.typical_trigger_rain_1h_mm
                    base_trig_6h = h_info.typical_trigger_rain_6h_mm
                    base_trig_3h = (base_trig_1h + base_trig_6h) * 0.45
                else:
                    # Non-hotspot cell baseline thresholds
                    base_trig_1h = 35.0
                    base_trig_6h = 80.0
                    base_trig_3h = 55.0

                horizon_base_triggers = {
                    1: base_trig_1h,
                    3: base_trig_3h,
                    6: base_trig_6h,
                }

                for h in horizons:
                    rf = horizon_rain.get(h, r1h)
                    base_trig = horizon_base_triggers.get(h, base_trig_1h)
                    eff_threshold = calibrate_hotspot_threshold(
                        base_trigger_mm=base_trig,
                        vulnerability_score=v_score,
                        rain_past_24h=rain_past_24h,
                    )

                    if event.city == "Patna" or event.event_id.startswith("EVT_PATNA_"):
                        wl, prob_score, tier, prov_str = compute_patna_event_target(
                            event_id=event.event_id,
                            cell_id=cid,
                            timestamp=ts,
                            vulnerability_score=v_score,
                            rainfall_mm=rf,
                            effective_threshold=eff_threshold,
                        )
                    else:
                        wl, prob_score, tier = compute_proxy_target(
                            rainfall_mm=rf,
                            effective_threshold=eff_threshold,
                            vulnerability_score=v_score,
                        )
                        prov_str = DEFAULT_PROVENANCE_STRING

                    sample = ProxySample(
                        sample_id=f"{event.event_id}_{cid}_{ts}_H{h}",
                        event_id=event.event_id,
                        cell_id=cid,
                        hotspot_id=hid,
                        timestamp=ts,
                        horizon=h,
                        rainfall_mm=rf,
                        rain_past_24h=rain_past_24h,
                        elevation=elev,
                        slope=slp,
                        flow_accumulation=flow_acc,
                        imperviousness=imp,
                        vulnerability_score=v_score,
                        trigger_rain_threshold=eff_threshold,
                        is_hotspot=is_hotspot,
                        waterlogged_proxy=wl,
                        flood_risk_proxy=prob_score,
                        proxy_risk_tier=tier,
                        is_proxy=True,
                        data_source=prov_str,
                    )
                    samples.append(sample)

    if output_dir:
        out_p = Path(output_dir)
        out_p.mkdir(parents=True, exist_ok=True)
        # Save JSON
        json_path = out_p / "proxy_training_dataset.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump([s.to_dict() for s in samples], f, indent=2)

        # Save CSV
        csv_path = out_p / "proxy_training_dataset.csv"
        if samples:
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(samples[0].to_dict().keys()))
                writer.writeheader()
                for s in samples:
                    writer.writerow(s.to_dict())

    return samples


def prepare_matrices_by_horizon(
    samples: List[ProxySample],
) -> Dict[int, Tuple[np.ndarray, np.ndarray]]:
    """Separates samples by horizon into feature matrix X and target vector y.

    Returns:
        Dict mapping horizon (1, 3, 6) -> (X, y)
    """
    by_h: Dict[int, List[ProxySample]] = {1: [], 3: [], 6: []}
    for s in samples:
        if s.horizon in by_h:
            by_h[s.horizon].append(s)

    matrices: Dict[int, Tuple[np.ndarray, np.ndarray]] = {}
    for h, h_samples in by_h.items():
        if not h_samples:
            continue
        X = np.array([s.to_feature_vector() for s in h_samples], dtype=np.float32)
        y = np.array([s.waterlogged_proxy for s in h_samples], dtype=np.int32)
        matrices[h] = (X, y)

    return matrices


def split_samples_by_events(
    samples: List[ProxySample],
    train_event_ids: Sequence[str],
    test_event_ids: Sequence[str],
    val_event_ids: Optional[Sequence[str]] = None,
) -> Tuple[List[ProxySample], List[ProxySample], List[ProxySample]]:
    """Splits samples strictly across independent historical events.

    Guarantees that no time steps or cell states from the evaluation events
    appear in the training dataset.

    Raises:
        ValueError: If training and test/validation event ID sets intersect.
    """
    train_set = set(train_event_ids)
    test_set = set(test_event_ids)
    val_set = set(val_event_ids or [])

    overlap_train_test = train_set.intersection(test_set)
    if overlap_train_test:
        raise ValueError(
            f"Event leakage violation: training and test event sets intersect: {overlap_train_test}"
        )

    overlap_train_val = train_set.intersection(val_set)
    if overlap_train_val:
        raise ValueError(
            f"Event leakage violation: training and validation event sets intersect: {overlap_train_val}"
        )

    train_samples = [s for s in samples if s.event_id in train_set]
    test_samples = [s for s in samples if s.event_id in test_set]
    val_samples = [s for s in samples if s.event_id in val_set]

    return train_samples, test_samples, val_samples


def get_available_event_ids(samples: Sequence[ProxySample]) -> List[str]:
    """Returns sorted distinct event IDs present across samples."""
    return sorted(list(set(s.event_id for s in samples)))


def verify_event_isolation(
    train_samples: Sequence[ProxySample],
    test_samples: Sequence[ProxySample],
) -> None:
    """Asserts that training and test samples are strictly disjoint in event space."""
    train_events = set(s.event_id for s in train_samples)
    test_events = set(s.event_id for s in test_samples)
    overlap = train_events.intersection(test_events)
    if overlap:
        raise ValueError(
            f"Event isolation failure: {len(overlap)} events shared between train and test: {overlap}"
        )
