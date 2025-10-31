import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY")

if not api_key:
    print("ERRO: GOOGLE_API_KEY não encontrada no .env. Verifique o arquivo .env.")
else:
    try:
        genai.configure(api_key=api_key)
        
        print("Buscando modelos disponíveis para sua chave de API...\n")
        
        found_models = False
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                print(f"Modelo encontrado: {m.name}")
                found_models = True
        
        if not found_models:
            print("--- NENHUM MODELO ENCONTRADO ---")
            print("Nenhum modelo com 'generateContent' foi retornado para sua chave.")

    except Exception as e:
        print(f"Ocorreu um erro ao tentar listar os modelos: {e}")