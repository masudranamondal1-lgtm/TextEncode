"""Wikidata API Adapter for TextEncode."""
import requests
from typing import List, Dict, Any

USER_AGENT = "TextEncode/0.6 (Digital Humanities research tool; https://github.com/masudranamondal1-lgtm/TextEncode)"

class WikidataProvider:
    name = "Wikidata"
    namespace = "wikidata"
    base_uri = "http://www.wikidata.org/entity/"

    def search(self, query: str, language: str = "en") -> List[Dict[str, Any]]:
        url = "https://www.wikidata.org/w/api.php"
        params = {
            "action": "wbsearchentities",
            "search": query,
            "language": language,
            "uselang": language,
            "format": "json",
            "limit": 10,
        }
        try:
            response = requests.get(url, params=params, timeout=10, headers={"User-Agent": USER_AGENT})
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"Wikidata API unavailable: {e}")

        results = []
        for item in data.get("search", []):
            results.append({
                "external_identifier": item.get("id", ""),
                "external_uri": f"http://www.wikidata.org/entity/{item.get('id', '')}",
                "external_label": item.get("label", ""),
                "external_description": item.get("description", ""),
                "alternative_names": ", ".join(item.get("aliases", []) or []),
                "provider": self.name,
            })
        return results
