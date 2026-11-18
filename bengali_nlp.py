"""Explainable, rule-based Bengali candidate extraction for TextEncode.

This module proposes review candidates. It does not perform authoritative
named-entity recognition and must not be treated as an automatic annotation.
Offsets always refer to the original passage string supplied by the caller.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone

import regex


class BengaliAnalyzer:
    def __init__(self):
        self.token_pattern = regex.compile(
            r"\p{Script=Bengali}[\p{Script=Bengali}\p{M}\u200c\u200d]*"
        )
        self.case_markers = {
            "গুলোতে": ["plural", "locative"], "গুলিতে": ["plural", "locative"],
            "গুলোকে": ["plural", "objective"], "গুলোর": ["plural", "genitive"],
            "টিতে": ["singular", "locative"], "টাতে": ["singular", "locative"],
            "গুলো": ["plural"], "গুলি": ["plural"], "দের": ["plural", "objective"],
            "টির": ["singular", "genitive"], "টার": ["singular", "genitive"],
            "ের": ["genitive"], "র": ["genitive"], "কে": ["objective"],
            "তে": ["locative"], "য়ে": ["locative"], "য়": ["locative"], "রা": ["plural"],
        }
        self.verb_endings = ["চ্ছে", "য়েছে", "তেছে", "লাম", "লেন", "বেন", "তাম", "তেন", "ছে", "লো", "বে", "ল", "ত"]
        self.stopwords = {
            "এই", "সেই", "একটা", "একটি", "সব", "কোন", "কেউ", "আর", "ও", "এবং", "কিন্তু", "তবে", "তাই", "কেন", "কেমন",
            "আমি", "তুমি", "সে", "তারা", "আমরা", "তোমরা", "আমার", "তোমার", "তার", "তাদের", "আমাদের", "তোমাদের",
            "কিছু", "অনেক", "নেই", "আছে", "ছিল", "হয়", "হবে", "করে", "থাকে", "যে", "যা", "যখন", "তখন", "না",
        }

    @staticmethod
    def normalize(text: str) -> str:
        return unicodedata.normalize("NFC", text)

    def analyze_token(self, token: str):
        token = self.normalize(token)
        if token in self.stopwords:
            return None
        for ending in self.verb_endings:
            if token.endswith(ending) and len(token) > len(ending) + 1:
                return {"surface": token, "type": "verb", "root": token[:-len(ending)], "rule": f"সম্ভাব্য ক্রিয়ারূপ: '{ending}' প্রত্যয়"}
        for suffix, features in self.case_markers.items():
            if token.endswith(suffix) and len(token) > len(suffix) + 1:
                return {"surface": token, "type": "noun", "root": token[:-len(suffix)], "features": features, "rule": f"বিভক্তি-সূচক '{suffix}' প্রত্যয় শনাক্ত"}
        return {"surface": token, "type": "noun", "root": token, "features": [], "rule": "পরিচিত বিভক্তি বা ক্রিয়াপ্রত্যয় মেলেনি; সম্ভাব্য প্রাতিপদিক"}

    def process_text(self, text: str):
        results = []
        # Match against the original string so the returned offsets remain usable
        # by TextEncode's current passage-level mention validation.
        for match in self.token_pattern.finditer(text):
            analysis = self.analyze_token(match.group())
            if analysis:
                analysis.update(start=match.start(), end=match.end())
                results.append(analysis)
        return results


_CATEGORY_CUES = {
    "River or hydrological feature": {"নদী", "নদ", "খাল", "বিল", "জল", "স্রোত", "ঘাট", "চর", "পুকুর", "ডোবা", "মোহনা"},
    "Place": {"গ্রাম", "শহর", "নগর", "জেলা", "দেশ", "মহল্লা", "বাড়ি", "বাজার", "মাঠ", "বন্দর", "স্টেশন"},
    "Person": {"বাবু", "মশাই", "জনাব", "শ্রী", "শ্রীমতী", "ডাক্তার", "অধ্যাপক", "মাস্টার", "মিঃ", "মিসেস"},
    "Plant": {"গাছ", "বৃক্ষ", "ফুল", "ধান", "ঘাস", "লতা", "পাতা", "বন"},
    "Animal": {"পাখি", "মাছ", "গরু", "হরিণ", "বাঘ", "কুকুর", "বিড়াল", "পশু", "পোকা"},
}
_HONORIFICS = {"শ্রী", "শ্রীমতী", "বাবু", "মশাই", "জনাব", "ডাক্তার", "অধ্যাপক", "মাস্টার", "মিঃ", "মিসেস"}


def _category_for_window(words: list[str], index: int, cat_map: dict):
    before = words[max(0, index - 2):index]
    after = words[index + 1:index + 3]
    window = set(before + after)
    # An honorific immediately before a token is a stronger, explicit clue.
    if before and before[-1] in _HONORIFICS and "person" in cat_map:
        return cat_map["person"], "Person", 0.82, f"আগের শব্দ '{before[-1]}' সম্মানসূচক/পদবাচক উপাধি; তাই Person প্রস্তাব।"
    for category, cues in _CATEGORY_CUES.items():
        category_id = cat_map.get(category.lower())
        matched = sorted(window.intersection(cues))
        if category_id is not None and matched:
            cue = matched[0]
            return category_id, category, 0.76, f"নিকটবর্তী প্রসঙ্গে '{cue}' শব্দটি {category} শ্রেণির ইঙ্গিত দেয়; গবেষক যাচাই প্রয়োজন।"
    return cat_map.get("other"), "Other", 0.42, "শব্দটি সম্ভাব্য নামপদ হিসেবে ধরা হয়েছে; নির্দিষ্ট শ্রেণির পর্যাপ্ত প্রসঙ্গ-প্রমাণ পাওয়া যায়নি।"


def _existing_name_set(existing_entities):
    names = set()
    for entity in existing_entities or []:
        for key in ("canonical_name", "alt_names"):
            if hasattr(entity, "get"):
                value = entity.get(key)
            else:
                try:
                    value = entity[key]
                except (KeyError, IndexError, TypeError):
                    value = None
            if value:
                names.add(unicodedata.normalize("NFC", str(value)).strip())
                if key == "alt_names":
                    names.update(x.strip() for x in re.split(r"[,;|\n]", str(value)) if x.strip())
    return names


def extract_candidates(passages: list, cat_map: dict, existing_entities: list, progress_callback=None) -> list[dict]:
    """Return DB-compatible candidate dictionaries with human-readable reasons."""
    analyzer = BengaliAnalyzer()
    existing_names = _existing_name_set(existing_entities)
    candidates = []
    total = len(passages)

    for passage_index, passage in enumerate(passages, start=1):
        text = passage["plain_text"] or ""
        matches = list(analyzer.token_pattern.finditer(text))
        words = [m.group() for m in matches]
        for i, match in enumerate(matches):
            surface = match.group()
            analysis = analyzer.analyze_token(surface)
            if not analysis or analysis["type"] != "noun":
                continue
            normalised_surface = unicodedata.normalize("NFC", surface).strip()
            if len(normalised_surface) < 2 or normalised_surface in existing_names:
                continue
            category_id, category_name, score, category_reason = _category_for_window(words, i, cat_map)
            if category_id is None:
                continue
            morphology_reason = analysis["rule"]
            explanation = (
                f"প্রস্তাবের কারণ: {morphology_reason}. {category_reason} "
                "এটি নিয়মভিত্তিক সম্ভাব্যতা, নিশ্চিত সত্তা-শনাক্তকরণ নয়।"
            )
            candidates.append({
                "doc_id": passage["doc_id"],
                "passage_id": passage["passage_id"],
                "surface_form": surface,
                "char_start": match.start(),
                "char_end": match.end(),
                "suggested_category_id": category_id,
                "confidence_score": score,
                "recognition_method": "bengali_rules_v1",
                "contextual_evidence": explanation,
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })
        if progress_callback:
            progress_callback(passage_index, total)
    return candidates
