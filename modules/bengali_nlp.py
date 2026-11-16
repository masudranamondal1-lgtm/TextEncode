"""Custom Bengali Morphological Engine."""
import regex
import unicodedata

class BengaliAnalyzer:
    def __init__(self):
        # 1. Unicode-safe tokenizer (from ChatGPT's recommendation)
        # Matches Bengali letters, marks, and handles ZWJ/ZWNJ
        self.token_pattern = regex.compile(r"\p{Script=Bengali}[\p{Script=Bengali}\p{M}\u200c\u200d]*")
        
        # 2. Case Markers (বিভক্তি) - Ordered by length for longest-match
        self.case_markers = {
            "গুলোতে": ["plural", "locative"],
            "গুলিতে": ["plural", "locative"],
            "গুলোকে": ["plural", "objective"],
            "গুলোর": ["plural", "genitive"],
            "টিতে": ["singular", "locative"],
            "টাতে": ["singular", "locative"],
            "গুলো": ["plural"],
            "গুলি": ["plural"],
            "দের": ["plural", "objective"],
            "টির": ["singular", "genitive"],
            "টার": ["singular", "genitive"],
            "ের": ["genitive"],
            "র": ["genitive"],
            "কে": ["objective"],
            "তে": ["locative"],
            "য়ে": ["locative"],
            "য়": ["locative"],
            "রা": ["plural"]
        }
        
        # 3. Verb Endings (তিঙ্গন্ত) to reject
        self.verb_endings = ["চ্ছে", "য়েছে", "তেছে", "লাম", "লেন", "বেন", "তাম", "তেন", "ছে", "লো", "বে", "ল", "ত"]
        
        # 4. Common pronouns and stopwords to ignore
        self.stopwords = {"এই", "সেই", "একটা", "একটি", "সব", "কোন", "কেউ", "আর", "ও", "এবং", "কিন্তু", "তবে", "তাই", "কেন", "কেমন", "আমি", "তুমি", "সে", "তারা", "আমরা", "তোমরা", "আমার", "তোমার", "তার", "তাদের", "আমাদের", "তোমাদের", "কিছু", "অনেক", "নেই", "আছে", "ছিল", "হয়", "হবে", "করে", "থাকে"}

    def normalize(self, text):
        return unicodedata.normalize("NFC", text)

    def analyze_token(self, token):
        """Applies morphological logic to a single word."""
        if token in self.stopwords:
            return None
            
        # Check for verbs (ক্রিয়া)
        for v_end in self.verb_endings:
            if token.endswith(v_end) and len(token) > len(v_end) + 1:
                # We don't completely reject it here, we just mark it
                return {"surface": token, "type": "verb", "root": token[:-len(v_end)]}

        # Check for case markers (বিভক্তি)
        for suffix, features in self.case_markers.items():
            if token.endswith(suffix) and len(token) > len(suffix) + 1:
                root = token[:-len(suffix)]
                return {
                    "surface": token, 
                    "type": "noun", 
                    "root": root, 
                    "features": features,
                    "rule": f"Removed case marker '-{suffix}'"
                }
                
        # If no suffix is found, it's likely a base noun (প্রাতিপদিক)
        return {"surface": token, "type": "noun", "root": token, "features": [], "rule": "Base word"}

    def process_text(self, text):
        """Tokenizes and analyzes an entire sentence/passage."""
        normalized_text = self.normalize(text)
        results = []
        
        for match in self.token_pattern.finditer(normalized_text):
            token = match.group()
            analysis = self.analyze_token(token)
            
            if analysis:
                # Add character offsets (relative to the normalized text)
                analysis["start"] = match.start()
                analysis["end"] = match.end()
                results.append(analysis)
                
        return results