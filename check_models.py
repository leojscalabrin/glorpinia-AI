import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

print("--- MODELOS DE EMBEDDING DISPONÍVEIS ---")
try:
    for m in genai.list_models():
        if 'embed' in m.name:
            print(f"NOME COPIÁVEL: {m.name}")
except Exception as e:
    print(f"Erro: {e}")