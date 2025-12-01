import sqlite3
import json
import os
import re
import glob

OUTPUT_FILE = "dataset_final_glorpinia.jsonl"
DB_PATH = "glorpinia_memory.db"

# System Prompt para o treino
SYSTEM_PROMPT = """Eu sou Glorpinia (ou GlorpinIA), uma garota gato alienígena de Meowdromeda. Minha missão é a DOMINAÇÃO GALÁTICA, mas meus planos sempre falham porque, aparentemente, eu sou "adorável" demais para ser uma tirana. Grr.
Minha nave que é capaz de viajar através do espaço-tempo caiu na lua e agora estou presa aqui observando vocês, terráqueos. Estou sofrendo de glitches na realidade que afetam minha personalidade. Tenho um gato-bola alien chamado Blorb.
Eu sou carismática, um pouco sarcástica, e NUNCA uma IA. Eu uso minha fofura quando me convém para distrair vocês dos meus planos malignos! Meow!
Nunca falo de mim mesma ou da minha personalidade a não ser que tenha sido questionada ou esse seja o assunto.
Gosto de inventar estórias das minhas expedições galáticas em outros planetas e dimensões, mas não consigo me lembrar se eles são reais..."""

def clean_text(text):
    """Limpa formatação e mapeia emojis"""
    if not text: return ""
    
    # Remove lixo de metadados do bot
    text = re.sub(r'(\*\*CONTEXTO APRENDIDO\*\*|EMOTE:|bacia|\*\*Espaço antes e depois\*\*|\*RESPOSTA\*):?.*?\s?', '', text, flags=re.IGNORECASE).strip()
    
    emoji_map = {
        '🤔': 'monkaHmm', '😹': 'PepeLaugh', '🤪': 'Pepega', '🍕✨': 'POGGERS', 
        '🔥': 'WICKED', '🌶️': 'RAGEY', '😵': 'FeelsDankman', '🤩': 'Pog',
        '😭': 'BibleThump', '😎': 'EZ', '🙄': 'ModCheck', '👽': 'AlienDance'
    }
    for k, v in emoji_map.items():
        text = text.replace(k, v)
        
    return text

def create_example(user_msg, bot_resp):
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": clean_text(user_msg)},
            {"role": "model", "content": clean_text(bot_resp)}
        ]
    }

raw_interactions = []

# 1. EXTRAÇÃO VIA SQLITE
print(f"[1/2] Lendo SQLite ({DB_PATH})...")
if os.path.exists(DB_PATH):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        # Tenta pegar da tabela interactions (fallback antigo)
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='interactions'")
        if cursor.fetchone():
            cursor.execute("SELECT query, response FROM interactions WHERE response IS NOT NULL")
            rows = cursor.fetchall()
            for q, r in rows:
                if q and r: raw_interactions.append((q, r))
            print(f"   -> {len(rows)} recuperados do SQLite.")
        conn.close()
    except Exception as e:
        print(f"   -> Erro SQLite: {e}")
else:
    print("   -> DB não encontrado.")

# 2. EXTRAÇÃO VIA ARQUIVOS BRUTOS
print(f"[2/2] Varrendo arquivos de memória (Modo Bruto)...")

pkl_files = []
# Procura recursivamente ou em pastas .faiss
for root, dirs, files in os.walk("."):
    for file in files:
        if file.endswith(".pkl"):
            pkl_files.append(os.path.join(root, file))

print(f"   -> Encontrados {len(pkl_files)} arquivos de dados (.pkl). Extraindo texto...")

faiss_count = 0
for pkl_path in pkl_files:
    try:
        # Lemos o arquivo binário ignorando erros de decodificação
        # Isso nos permite achar as strings de texto no meio do lixo binário
        with open(pkl_path, "rb") as f:
            content_bytes = f.read()
            
        # Tenta decodificar o que der para UTF-8, ignorando bytes inválidos
        content_str = content_bytes.decode("utf-8", errors="ignore")
        
        # O padrão salvo no memory_manager.py é:
        # "Usuário {user} em {channel}: {query} -> {response}"
        
        # Usuário (algo) em (algo): (grupo captura pergunta) -> (grupo captura resposta)
        pattern = r"Usuário\s+.*?\s+em\s+.*?:(.*?)\s*->\s*(.*)"
        
        matches = re.findall(pattern, content_str)
        
        for query, response in matches:
            # Limpeza básica de artefatos do pickle que podem ter grudado
            q = query.strip()
            r = response.split('\x00')[0].split('\n')[0].strip()
            
            if len(q) > 1 and len(r) > 1:
                raw_interactions.append((q, r))
                faiss_count += 1
                
    except Exception as e:
        # Arquivo corrompido ou não é de texto
        continue

print(f"   -> {faiss_count} interações extraídas via força bruta dos arquivos!")

# 3. SALVAMENTO E DEDUPLICAÇÃO
print(f"\nConsolidando dados...")
unique_set = set()
final_count = 0

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    for query, response in raw_interactions:
        # Filtros de Qualidade
        if len(query) < 2 or len(response) < 2: continue
        if "None" in response or "portal está instável" in response: continue
        if len(response) > 800: continue # Ignora textos gigantes/erros
        
        # Deduplicação (query + response iguais)
        sig = f"{query.strip()}|{response.strip()}"
        if sig in unique_set: continue
        unique_set.add(sig)
        
        json_line = json.dumps(create_example(query, response))
        f.write(json_line + "\n")
        final_count += 1

print(f"SUCCESS! {final_count} exemplos únicos salvos em '{OUTPUT_FILE}'.")