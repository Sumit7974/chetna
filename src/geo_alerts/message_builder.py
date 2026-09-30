"""Message builder for Chetna automatic geo-targeted public warnings.

Generates concise, standardized bilingual emergency warnings and public advisories
in English and Hindi without making unsupported claims.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from src.geo_alerts.policy import PublicWarningAction
from src.geo_alerts.zone_targeting import GeoZoneTarget

# Standard prototype notices
PROTOTYPE_DISCLAIMER_EN = "This is an automated prototype alert for early warning decision support."
PROTOTYPE_DISCLAIMER_HI = "यह पूर्व चेतावनी निर्णय-सहायता के लिए एक स्वचालित प्रोटोटाइप अलर्ट है।"

# Safe route disclaimer preserved from Chetna F2
ROUTING_DISCLAIMER_EN = "Decision-support navigation path only; not a guaranteed safe evacuation route."
ROUTING_DISCLAIMER_HI = "केवल निर्णय-सहायता नेविगेशन मार्ग; कोई गारंटीकृत सुरक्षित निकासी मार्ग नहीं।"


@dataclass
class BilingualWarningMessage:
    """Structured container holding English and Hindi versions of a public warning."""

    zone_id: str
    zone_name: str
    severity: str
    warning_type: str  # 'EMERGENCY_BROADCAST' or 'PUBLIC_ADVISORY'
    headline_en: str
    headline_hi: str
    body_en: str
    body_hi: str
    action_en: str
    action_hi: str
    disclaimer_en: str = PROTOTYPE_DISCLAIMER_EN
    disclaimer_hi: str = PROTOTYPE_DISCLAIMER_HI

    @property
    def full_text_en(self) -> str:
        """Full formatted English warning message."""
        return f"{self.headline_en}: {self.body_en} {self.action_en} [{self.disclaimer_en}]"

    @property
    def full_text_hi(self) -> str:
        """Full formatted Hindi warning message."""
        return f"{self.headline_hi}: {self.body_hi} {self.action_hi} [{self.disclaimer_hi}]"

    def get_by_language(self, language: str = "en") -> str:
        """Retrieve full warning text formatted for requested language ('en' or 'hi')."""
        if language.lower().startswith("hi"):
            return self.full_text_hi
        return self.full_text_en

    def to_dict(self) -> Dict[str, str]:
        """Convert message to dictionary."""
        return {
            "zone_id": self.zone_id,
            "zone_name": self.zone_name,
            "severity": self.severity,
            "warning_type": self.warning_type,
            "headline_en": self.headline_en,
            "headline_hi": self.headline_hi,
            "body_en": self.body_en,
            "body_hi": self.body_hi,
            "action_en": self.action_en,
            "action_hi": self.action_hi,
            "full_text_en": self.full_text_en,
            "full_text_hi": self.full_text_hi,
            "disclaimer_en": self.disclaimer_en,
            "disclaimer_hi": self.disclaimer_hi,
        }


ZONE_NAME_HINDI_MAP: Dict[str, str] = {
    "kankarbagh": "कंकड़बाग",
    "rajendra nagar": "राजेन्द्र नगर",
    "patliputra": "पाटलिपुत्र",
    "boring canal road": "बोरिंग कैनाल रोड",
    "boring road": "बोरिंग रोड",
    "bazar samiti": "बाजार समिति",
    "gardanibagh": "गर्दनीबाग",
    "saidpur": "सैदपुर",
    "kurji / digha": "कुर्जी / दीघा",
    "pahari / zero mile": "पहाड़ी / जीरो माइल",
    "gandhi maidan": "गांधी मैदान",
    "patna": "पटना",
    "patna municipal area": "पटना नगर निगम क्षेत्र",
}


def translate_zone_name_to_hindi(zone_name: str) -> str:
    """Translate zone name into Hindi if known, else return original."""
    zn_clean = zone_name.strip().lower()
    for k, v in ZONE_NAME_HINDI_MAP.items():
        if k in zn_clean:
            return v
    return zone_name


class PublicWarningMessageBuilder:
    """Builder generating standardized English and Hindi public warnings."""

    def build_warning(
        self,
        target: GeoZoneTarget,
        action: PublicWarningAction = PublicWarningAction.EMERGENCY_BROADCAST,
        water_level_cm: Optional[float] = None,
        rainfall_rate_mm_h: Optional[float] = None,
    ) -> BilingualWarningMessage:
        """Build bilingual warning message tailored to the zone and evaluated action."""
        zone_name = target.zone_name
        zone_name_hi = translate_zone_name_to_hindi(zone_name)
        severity = target.risk_level.upper()

        if action == PublicWarningAction.EMERGENCY_BROADCAST:
            headline_en = "FLOOD WARNING"
            headline_hi = "बाढ़ चेतावनी"

            body_en = f"Critical flood risk and severe stormwater stagnation detected in {zone_name}."
            body_hi = f"{zone_name_hi} क्षेत्र में अत्यधिक जलभराव एवं गंभीर बाढ़ जोखिम दर्ज किया गया है।"

            action_en = "Avoid waterlogged roads and move to a safer location if advised by local authorities."
            action_hi = "जलमग्न सड़कों से बचें और स्थानीय अधिकारियों की सलाह पर सुरक्षित स्थान की ओर जाएँ।"

            warning_type = "EMERGENCY_BROADCAST"

        elif action == PublicWarningAction.PUBLIC_ADVISORY:
            headline_en = "FLOOD ADVISORY"
            headline_hi = "बाढ़ सलाह"

            body_en = f"Elevated waterlogging risk detected across low-elevation sectors of {zone_name}."
            body_hi = f"{zone_name_hi} के निचले इलाकों में जलभराव का बढ़ा हुआ जोखिम दर्ज किया गया है।"

            action_en = "Avoid low-lying underpasses and monitor official advisories."
            action_hi = "निचले सबवे/अंडरपास से बचें और आधिकारिक सूचनाओं पर नजर रखें।"

            warning_type = "PUBLIC_ADVISORY"

        else:
            headline_en = "MONITORING ADVISORY"
            headline_hi = "निगरानी सलाह"

            body_en = f"Normal drainage conditions monitored in {zone_name}."
            body_hi = f"{zone_name_hi} में सामान्य जल निकासी स्थिति दर्ज की गई है।"

            action_en = "No immediate flood hazard. Routine precautions apply."
            action_hi = "कोई तात्कालिक खतरा नहीं। सामान्य सावधानी बरतें।"

            warning_type = "INFO_UPDATE"

        # Optional measured context if explicitly verified
        if water_level_cm is not None and water_level_cm > 0:
            body_en += f" (Sensor telemetry: {water_level_cm:.0f} cm water level)."
            body_hi += f" (सेंसर रीडिंग: {water_level_cm:.0f} सेमी जल स्तर)।"

        return BilingualWarningMessage(
            zone_id=target.zone_id,
            zone_name=zone_name,
            severity=severity,
            warning_type=warning_type,
            headline_en=headline_en,
            headline_hi=headline_hi,
            body_en=body_en,
            body_hi=body_hi,
            action_en=action_en,
            action_hi=action_hi,
            disclaimer_en=PROTOTYPE_DISCLAIMER_EN,
            disclaimer_hi=PROTOTYPE_DISCLAIMER_HI,
        )


_default_message_builder = PublicWarningMessageBuilder()


def build_bilingual_warning(
    target: GeoZoneTarget,
    action: PublicWarningAction = PublicWarningAction.EMERGENCY_BROADCAST,
    water_level_cm: Optional[float] = None,
    rainfall_rate_mm_h: Optional[float] = None,
) -> BilingualWarningMessage:
    """Convenience helper to generate bilingual warning message."""
    return _default_message_builder.build_warning(
        target=target,
        action=action,
        water_level_cm=water_level_cm,
        rainfall_rate_mm_h=rainfall_rate_mm_h,
    )
