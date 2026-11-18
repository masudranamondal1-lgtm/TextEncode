"""Wikidata API Adapter for TextEncode."""
import requests
from typing import List, Dict, Any

class WikidataProvider:
    name = "Wikidata"
    namespace = "wikidata"
    base_uri = "http://www.wikidata.org/entity/"
    
    def search(self, query: str, language: str = "en") -> List[Dict[str, Any]]:
        """Search Wikidata for entities matching the query."""
        url = "https://www.wikidata.org/w/api.php"
        params = {
            "action": "wbsearchentities",
            "search": query,
            "language": language,
            "format": "json",
            "limit": 10
        }
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            results = []
            for item in data.get("search", []):
                results.append({
                    "external_identifier": item.get("id", ""),
                    "external_uri": f"http://www.wikidata.org/entity/{item.get('id', '')}",
                    "external_label": item.get("label", ""),
                    "external_description": item.get("description", ""),
                    "alternative_names": ", ".join(item.get("aliases", [])),
                    "provider": self.name
                })
            return results
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"Wikidata API unavailable: {e}")

    def get_record(self, identifier: str) -> Dict[str, Any]:
        """Retrieve full record for a Wikidata entity (simplified)."""
        url = f"https://www.wikidata.org/wiki/Special:EntityData/{identifier}.json"
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException:
            return {}
