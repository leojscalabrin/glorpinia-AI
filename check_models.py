from google import genai
import os
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key) if api_key else genai.Client()

print("--- MODELOS DE EMBEDDING DISPONÍVEIS ---")
try:
    for m in client.models.list():
        if 'embed' in m.name:
            print(f"NOME COPIÁVEL: {m.name}")
except Exception as e:
    print(f"Erro: {e}")
