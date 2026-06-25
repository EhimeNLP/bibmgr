import difflib

def calculate_similarity(original_text: str, found_text: str) -> float:
    """
    2つの文字列の類似度を0.0〜1.0のスコアで返す
    """
    if not original_text or not found_text:
        return 0.0
    
    str1 = original_text.lower()
    str2 = found_text.lower()
    
    return difflib.SequenceMatcher(None, str1, str2).ratio()