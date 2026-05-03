import os
import re
import google.generativeai as genai
from google.generativeai.types import SafetySettingDict, HarmCategory, HarmBlockThreshold

safety_settings: SafetySettingDict = [
    {
        "category": HarmCategory.HARM_CATEGORY_HARASSMENT,
        "threshold": HarmBlockThreshold.BLOCK_NONE,
    },
    {
        "category": HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        "threshold": HarmBlockThreshold.BLOCK_NONE,
    },
    {
        "category": HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
        "threshold": HarmBlockThreshold.BLOCK_NONE,
    },
    {
        "category": HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
        "threshold": HarmBlockThreshold.BLOCK_NONE,
    },
]

api_key = os.getenv("GEMINI_API_KEY")
if api_key:
    genai.configure(api_key=api_key)

def extract_core_concept_via_llm(title: str, raw_text: str = "") -> str:
    if not title or not api_key:
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
        model = genai.GenerativeModel(
            model_name='gemini-flash-lite-latest',
            safety_settings=safety_settings
        )
        
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.0,
                max_output_tokens=15,
            )
        )
        
        extracted = response.text.strip()
        cleaned = re.sub(r'[^a-zA-Z0-9]', '', extracted).lower()
        
        return cleaned if cleaned else "unknown"
        
    except Exception as e:
        print(f"[LLM Extractor] API Error: {e}")
        return "unknown"