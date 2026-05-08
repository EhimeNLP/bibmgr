import re
from google import genai
from google.genai import types
from core.config import settings

client = genai.Client(api_key=settings.gemini_api_key)

def extract_core_concept_via_llm(title: str, raw_text: str = "") -> str:
    if not title:
        return "unknown"
        
    context = raw_text[:500] if raw_text else ""
    
    prompt = f"""
You are an academic paper bibliography information extraction assistant.
From the following paper title (and the beginning of the text), please extract the representative "model name", "dataset name", or "most important technical term" as a single word.

【Rules】
- Output only the extracted single word (alphanumeric).
- Do not include any additional explanation, symbols, or punctuation.
- If spaces are included, remove them and concatenate (e.g., "Vision Transformer" -> "VisionTransformer").
- If there is no specific unique model name, select one key technical term from the paper.

Title: {title}
Context: {context}
"""

    try:
        response = client.models.generate_content(
            model=settings.model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=settings.temperature,
                max_output_tokens=settings.max_output_tokens,
                safety_settings=[
                    types.SafetySetting(
                        category="HARM_CATEGORY_HARASSMENT",
                        threshold="BLOCK_NONE"
                    ),
                    types.SafetySetting(
                        category="HARM_CATEGORY_HATE_SPEECH",
                        threshold="BLOCK_NONE"
                    ),
                ]
            )
        )
        
        if not response.text:
            return "unknown"

        extracted = response.text.strip()
        cleaned = re.sub(r'[^a-zA-Z0-9]', '', extracted).lower()
        
        return cleaned if cleaned else "unknown"
        
    except Exception as e:
        print(f"[LLM Extractor] API Error with New SDK: {e}")
        return "unknown"