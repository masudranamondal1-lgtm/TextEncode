"""GeoNames API Adapter for TextEncode."""
import os
import requests
from typing import List, Dict, Any

USER_AGENT = "TextEncode/0.6 (Digital Humanities research tool)"

class GeoNamesProvider:
    name = "GeoNames"
    namespace = "geonames"
    base_uri = "http://sws.geonames.org/"

    def __init__(self):
        # Free account: http://www.geonames.org/login  -> set GEONAMES_USERNAME
        self.username = (os.environ.get("GEONAMES_USERNAME") or "").strip()

    def is_configured(self) -> bool:
        return bool(self.username)

    def search(self, query: str, language: str = "en") -> List[Dict[str, Any]]:
        if not self.is_configured():
            raise RuntimeError(
                "GeoNames requires a free username. Set the environment "
                "variable GEONAMES_USERNAME and restart the app."
            )
        url = "https://secure.geonames.org/searchJSON"
        params = {"q": query, "maxRows": 10, "username": self.username, "lang": language}
        try:
            response = requests.get(
                url, params=params, timeout=10,
                headers={"User-Agent": USER_AGENT},
            )
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"GeoNames API unavailable: {e}")

        results = []
        for g in data.get("geonames", []):
            gid = g.get("geonameId", "")
            alt = g.get("alternatenames", [])
            results.append({
                "external_identifier": str(gid),
                "external_uri": f"http://sws.geonames.org/{gid}/",
                "external_label": g.get("name", ""),
                "external_description": (
                    f"{g.get('fcl', '')} {g.get('fcode', '')} · {g.get('countryCode', '')}"
                ),
                "alternative_names": ", ".join(alt) if isinstance(alt, list) else "",
                "latitude": float(g["lat"]) if g.get("lat") else None,
                "longitude": float(g["lng"]) if g.get("lng") else None,
                "provider": self.name,
            })
        return results