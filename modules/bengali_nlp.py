"""Custom Bengali Morphological Engine."""
import regex
import unicodedata
from datetime import datetime, timezone

class BengaliAnalyzer:
    def __init__(self):
        self.token_pattern = regex.compile(r"\p{Script=Bengali}[\p{Script=Bengali}\p{M}\u200c\u200d]*")
        self.case_markers = {
            "গুলোতে": ["plural", "locative"], "গুলিতে": ["plural", "locative"],
            "গুলোকে": ["plural", "objective"], "গুলোর": ["plural", "genitive"],
            "টিতে": ["singular", "locative"], "টাতে": ["singular", "locative"],
            "গুলো": ["plural"], "গুলি": ["plural"], "দের": ["plural", "objective"],
            "টির": ["singular", "genitive"], "টার": ["singular", "genitive"],
            "ের": ["genitive"], "র": ["genitive"], "কে": ["objective"],
            "তে": ["locative"], "য়ে": ["locative"], "য়": ["locative"], "রা": ["plural"]
        }
        self.verb_endings = ["চ্ছে", "য়েছে", "তেছে", "লাম", "লেন", "বেন", "তাম", "তেন", "ছে", "লো", "বে", "ল", "ত"]
        self.stopwords = {"এই", "সেই", "একটা", "একটি", "সব", "কোন", "কেউ", "আর", "ও", "এবং", "কিন্তু", "তবে", "তাই", "কেন", "কেমন", "আমি", "তুমি", "সে", "তারা", "আমরা", "তোমরা", "আমার", "তোমার", "তার", "তাদের", "আমাদের", "তোমাদের", "কিছু", "অনেক", "নেই", "আছে", "ছিল", "হয়", "হবে", "করে", "থাকে"}

    def normalize(self, text):
        return unicodedata.normalize("NFC", text)

    def analyze_token(self, token):
        if token in self.stopwords:
            return None
        for v_end in self.verb_endings:
            if token.endswith(v_end) and len(token) > len(v_end) + 1:
                return {"surface": token, "type": "verb", "root": token[:-len(v_end)]}
        for suffix, features in self.case_markers.items():
            if token.endswith(suffix) and len(token) > len(suffix) + 1:
                root = token[:-len(suffix)]
                return {"surface": token, "type": "noun", "root": root, "features": features, "rule": f"Removed case marker '-{suffix}'"}
        return {"surface": token, "type": "noun", "root": token, "features": [], "rule": "Base word"}

    def process_text(self, text):
        normalized_text = self.normalize(text)
        results = []
        for match in self.token_pattern.finditer(normalized_text):
            token = match.group()
            analysis = self.analyze_token(token)
            if analysis:
                analysis["start"] = match.start()
                analysis["end"] = match.end()
                results.append(analysis)
        return results

# MUST BE AT MODULE LEVEL (NO INDENTATION)
def extract_candidates(passages: list, cat_map: dict, existing_entities: list, progress_callback=None) -> list[dict]:
    analyzer = BengaliAnalyzer()
    candidates = []
    
    known_entities = {}
    for ent in existing_entities:
        known_entities[ent["canonical_name"].lower()] = ent["category_id"]
        if ent.get("alt_names"):
            for alias in ent["alt_names"].split(","):
                known_entities[alias.strip().lower()] = ent["category_id"]

    total = len(passages)
    for idx, passage in enumerate(passages):
        if progress_callback:
            progress_callback(idx + 1, total)
            
        text = passage["plain_text"]
        if not text:
            continue
            
        analyzed_tokens = analyzer.process_text(text)
        
        for token_data in analyzed_tokens:
            if token_data["type"] != "noun":
                continue
                
            surface = token_data["surface"]
            root = token_data["root"]
            
            suggested_cat_id = None
            method = "Bengali Noun Root Extraction"
            confidence = 0.4
            reason = f"Identified as a base noun/root ('{root}'). No exact entity match found."
            
            if root.lower() in known_entities:
                suggested_cat_id = known_entities[root.lower()]
                method = "Known Entity Alias/Root Match"
                confidence = 0.85
                reason = f"Root '{root}' exactly matches an existing entity alias or canonical name."
            else:
                suggested_cat_id = cat_map.get("other") or cat_map.get("person")

            if suggested_cat_id is None:
                continue

            candidates.append({
                "doc_id": passage["doc_id"],
                "passage_id": passage["passage_id"],
                "surface_form": surface,
                "char_start": token_data["start"],
                "char_end": token_data["end"],
                "suggested_category_id": suggested_cat_id,
                "confidence_score": confidence,
                "recognition_method": method,
                "recognition_reason": reason,
                "contextual_evidence": f"Features: {token_data.get('features', [])}",
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")
            })
            
    return candidates