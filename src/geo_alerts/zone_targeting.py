"""Geo-targeting component for Chetna automatic public warnings.

Maps risk predictions, cell IDs, telemetry nodes, or coordinates to authoritative
geographic zones without requiring citizen phone numbers or contact lists.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

DEFAULT_HOTSPOTS_PATH = Path("data/m1/hotspots.json")


@dataclass
class GeoZoneTarget:
    """Represents an affected geographic zone target for public warning."""

    zone_id: str
    zone_name: str
    risk_level: str = "INFO"
    risk_score: Optional[float] = None
    target_type: str = "GEO_ZONE"
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    ward: Optional[int] = None
    circle: Optional[str] = None
    cell_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert target to dictionary."""
        d = asdict(self)
        return d


# Known fallback registry of canonical Patna municipal zones/hotspots
CANONICAL_PATNA_ZONES: List[Dict[str, Any]] = [
    {
        "zone_id": "ZONE_KAN",
        "zone_name": "Kankarbagh",
        "aliases": ["kankarbagh", "cell_kan_01", "sens_pat_02", "hs02"],
        "cell_id": "CELL_KAN_01",
        "ward": 45,
        "circle": "Kankarbagh Circle",
        "latitude": 25.5945,
        "longitude": 85.1582,
    },
    {
        "zone_id": "ZONE_RAJ",
        "zone_name": "Rajendra Nagar",
        "aliases": ["rajendra nagar", "cell_raj_01", "sens_pat_01", "hs01"],
        "cell_id": "CELL_RAJ_01",
        "ward": 43,
        "circle": "Kankarbagh / Rajendra Nagar Circle",
        "latitude": 25.6012,
        "longitude": 85.1634,
    },
    {
        "zone_id": "ZONE_PAT",
        "zone_name": "Patliputra",
        "aliases": ["patliputra", "cell_pat_01", "hs03"],
        "cell_id": "CELL_PAT_01",
        "ward": 22,
        "circle": "Patliputra Circle",
        "latitude": 25.6280,
        "longitude": 85.1050,
    },
    {
        "zone_id": "ZONE_BOR",
        "zone_name": "Boring Canal Road",
        "aliases": ["boring canal road", "boring road", "cell_bor_01", "hs04"],
        "cell_id": "CELL_BOR_01",
        "ward": 25,
        "circle": "New Capital Circle",
        "latitude": 25.6130,
        "longitude": 85.1200,
    },
    {
        "zone_id": "ZONE_BAZ",
        "zone_name": "Bazar Samiti",
        "aliases": ["bazar samiti", "cell_baz_01", "hs05"],
        "cell_id": "CELL_BAZ_01",
        "ward": 48,
        "circle": "Kankarbagh Circle",
        "latitude": 25.6080,
        "longitude": 85.1850,
    },
    {
        "zone_id": "ZONE_GAR",
        "zone_name": "Gardanibagh",
        "aliases": ["gardanibagh", "cell_gar_01", "hs06"],
        "cell_id": "CELL_GAR_01",
        "ward": 14,
        "circle": "New Capital Circle",
        "latitude": 25.5910,
        "longitude": 85.1220,
    },
    {
        "zone_id": "ZONE_SAI",
        "zone_name": "Saidpur",
        "aliases": ["saidpur", "cell_sai_01", "sens_pat_03", "hs07"],
        "cell_id": "CELL_SAI_01",
        "ward": 50,
        "circle": "Bankipur Circle",
        "latitude": 25.6030,
        "longitude": 85.1670,
    },
    {
        "zone_id": "ZONE_KUR",
        "zone_name": "Kurji / Digha",
        "aliases": ["kurji", "digha", "cell_kur_01", "hs08"],
        "cell_id": "CELL_KUR_01",
        "ward": 1,
        "circle": "Patliputra Circle",
        "latitude": 25.6420,
        "longitude": 85.1020,
    },
    {
        "zone_id": "ZONE_PAH",
        "zone_name": "Pahari / Zero Mile",
        "aliases": ["pahari", "zero mile", "cell_pah_01", "hs09"],
        "cell_id": "CELL_PAH_01",
        "ward": 55,
        "circle": "Pahari Drainage Zone",
        "latitude": 25.5780,
        "longitude": 85.1890,
    },
    {
        "zone_id": "ZONE_GAN",
        "zone_name": "Gandhi Maidan",
        "aliases": ["gandhi maidan", "cell_gan_01", "hs10"],
        "cell_id": "CELL_GAN_01",
        "ward": 38,
        "circle": "Bankipur Circle",
        "latitude": 25.6210,
        "longitude": 85.1440,
    },
]


class GeoTargetingService:
    """Service resolving risk evaluations into geographic zone targets."""

    def __init__(self, hotspots_path: Union[str, Path] = DEFAULT_HOTSPOTS_PATH) -> None:
        self.hotspots_path = Path(hotspots_path)
        self._zone_cache: List[Dict[str, Any]] = []
        self._load_zones()

    def _load_zones(self) -> None:
        """Load zones from hotspots.json or use canonical defaults."""
        zones: List[Dict[str, Any]] = list(CANONICAL_PATNA_ZONES)
        if self.hotspots_path.exists():
            try:
                with open(self.hotspots_path, "r", encoding="utf-8") as f:
                    hotspots = json.load(f)
                if isinstance(hotspots, list):
                    for h in hotspots:
                        if not isinstance(h, dict):
                            continue
                        hid = str(h.get("hotspot_id", "")).strip()
                        name = str(h.get("name", "")).strip()
                        zone_raw = str(h.get("zone", "")).strip()
                        cell_id = str(h.get("cell_id", "")).strip()
                        lat = float(h.get("latitude", 25.6093))
                        lon = float(h.get("longitude", 85.1376))
                        ward = h.get("ward")

                        # Determine primary zone name
                        zone_name = name
                        if " (" in zone_raw:
                            zone_clean = zone_raw.split(" (")[0]
                        else:
                            zone_clean = zone_raw
                        if "/" in zone_clean:
                            candidate = zone_clean.split("/")[0].strip()
                            if candidate:
                                zone_name = candidate
                        elif zone_clean:
                            zone_name = zone_clean

                        zone_id = f"ZONE_{hid}" if hid else f"ZONE_{cell_id}"
                        aliases = [hid.lower(), name.lower(), cell_id.lower(), zone_raw.lower()]

                        # Check if already present in canonical list
                        existing = next((z for z in zones if z["cell_id"] == cell_id or z["zone_id"] == zone_id), None)
                        if existing:
                            existing["latitude"] = lat
                            existing["longitude"] = lon
                            if ward:
                                existing["ward"] = ward
                            for a in aliases:
                                if a and a not in existing["aliases"]:
                                    existing["aliases"].append(a)
                        else:
                            zones.append({
                                "zone_id": zone_id,
                                "zone_name": zone_name,
                                "aliases": aliases,
                                "cell_id": cell_id,
                                "ward": ward,
                                "circle": zone_raw,
                                "latitude": lat,
                                "longitude": lon,
                            })
            except Exception as exc:
                logger.warning("Could not parse hotspots file at %s: %s", self.hotspots_path, exc)

        self._zone_cache = zones

    def resolve_zone(
        self,
        risk_source: Any = None,
        cell_id: Optional[str] = None,
        node_id: Optional[str] = None,
        location_name: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        risk_level: Optional[str] = None,
        risk_score: Optional[float] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> GeoZoneTarget:
        """Resolve a risk event into a GeoZoneTarget.

        Extracts information from:
        - RiskPrediction object (.cell_id, .level, .probability)
        - EvaluationResult object (.node_id, .affected_area, .severity)
        - SensorReading (.node_id)
        - or explicit arguments.
        """
        extracted_cell = cell_id
        extracted_node = node_id
        extracted_loc = location_name
        extracted_lat = latitude
        extracted_lon = longitude
        extracted_level = risk_level
        extracted_score = risk_score
        meta: Dict[str, Any] = dict(extra_metadata or {})

        if risk_source is not None:
            # Check for dict-like
            if isinstance(risk_source, dict):
                extracted_cell = extracted_cell or risk_source.get("cell_id")
                extracted_node = extracted_node or risk_source.get("node_id")
                extracted_loc = extracted_loc or risk_source.get("location") or risk_source.get("affected_area") or risk_source.get("zone_name")
                extracted_lat = extracted_lat if extracted_lat is not None else risk_source.get("latitude")
                extracted_lon = extracted_lon if extracted_lon is not None else risk_source.get("longitude")
                extracted_level = extracted_level or risk_source.get("risk_level") or risk_source.get("level") or risk_source.get("severity")
                extracted_score = extracted_score if extracted_score is not None else risk_source.get("risk_score") or risk_source.get("probability")
            # Check for RiskPrediction
            elif hasattr(risk_source, "cell_id"):
                extracted_cell = extracted_cell or getattr(risk_source, "cell_id")
                extracted_level = extracted_level or getattr(risk_source, "level", None)
                extracted_score = extracted_score if extracted_score is not None else getattr(risk_source, "probability", None)
            # Check for EvaluationResult
            if hasattr(risk_source, "node_id"):
                extracted_node = extracted_node or getattr(risk_source, "node_id")
                extracted_loc = extracted_loc or getattr(risk_source, "affected_area", None)
                if not extracted_level:
                    sev = getattr(risk_source, "severity", None)
                    extracted_level = sev.value if hasattr(sev, "value") else (str(sev) if sev else None)
            # Check for SensorReading
            if hasattr(risk_source, "latitude") and extracted_lat is None:
                extracted_lat = getattr(risk_source, "latitude", None)
            if hasattr(risk_source, "longitude") and extracted_lon is None:
                extracted_lon = getattr(risk_source, "longitude", None)

        norm_level = str(extracted_level).upper() if extracted_level else "INFO"
        if norm_level == "SEVERE":
            norm_level = "CRITICAL"

        # Match against known zones
        best_match: Optional[Dict[str, Any]] = None

        search_tokens = []
        if extracted_cell:
            search_tokens.append(str(extracted_cell).strip().lower())
        if extracted_node:
            search_tokens.append(str(extracted_node).strip().lower())
        if extracted_loc:
            search_tokens.append(str(extracted_loc).strip().lower())

        for token in search_tokens:
            for z in self._zone_cache:
                if token in z["aliases"] or token == z["zone_id"].lower() or token in z["zone_name"].lower():
                    best_match = z
                    break
            if best_match:
                break

        # Coordinate matching if lat/lon provided
        if not best_match and extracted_lat is not None and extracted_lon is not None:
            min_dist = float("inf")
            for z in self._zone_cache:
                d = math.hypot(extracted_lat - z["latitude"], extracted_lon - z["longitude"])
                if d < min_dist:
                    min_dist = d
                    best_match = z

        if best_match:
            return GeoZoneTarget(
                zone_id=best_match["zone_id"],
                zone_name=best_match["zone_name"],
                risk_level=norm_level,
                risk_score=float(extracted_score) if extracted_score is not None else None,
                target_type="GEO_ZONE",
                latitude=best_match.get("latitude"),
                longitude=best_match.get("longitude"),
                ward=best_match.get("ward"),
                circle=best_match.get("circle"),
                cell_id=extracted_cell or best_match.get("cell_id"),
                metadata=meta,
            )

        # Fallback to general zone
        fallback_name = extracted_loc or extracted_cell or extracted_node or "Patna Municipal Area"
        fallback_id = f"ZONE_{str(extracted_cell or extracted_node or 'PATNA').upper()}"
        return GeoZoneTarget(
            zone_id=fallback_id,
            zone_name=fallback_name,
            risk_level=norm_level,
            risk_score=float(extracted_score) if extracted_score is not None else None,
            target_type="GEO_ZONE",
            latitude=extracted_lat or 25.6093,
            longitude=extracted_lon or 85.1376,
            ward=None,
            circle="Patna Urban Basin",
            cell_id=extracted_cell,
            metadata=meta,
        )


_default_geo_targeting_service = GeoTargetingService()


def resolve_geo_zone(
    risk_source: Any = None,
    cell_id: Optional[str] = None,
    node_id: Optional[str] = None,
    location_name: Optional[str] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    risk_level: Optional[str] = None,
    risk_score: Optional[float] = None,
) -> GeoZoneTarget:
    """Convenience helper to resolve a geographic zone target."""
    return _default_geo_targeting_service.resolve_zone(
        risk_source=risk_source,
        cell_id=cell_id,
        node_id=node_id,
        location_name=location_name,
        latitude=latitude,
        longitude=longitude,
        risk_level=risk_level,
        risk_score=risk_score,
    )
