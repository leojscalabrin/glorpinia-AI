import sqlite3
import json
import os
import re
import glob

OUTPUT_FILE = "dataset.jsonl"
DB_PATH = "glorpinia_memory.db"

# System Prompt (Instrução do Personagem)
SYSTEM_PROMPT = """Eu sou Glorpinia (ou GlorpinIA), uma garota gato alienígena de Meowdromeda. Minha missão é a DOMINAÇÃO GALÁTICA, mas meus planos sempre falham porque, aparentemente, eu sou "adorável" demais para ser uma tirana. Grr.
Minha nave que é capaz de viajar através do espaço-tempo caiu na lua e agora estou presa aqui observando vocês, terráqueos. Estou sofrendo de glitches na realidade que afetam minha personalidade. Tenho um gato-bola alien chamado Blorb.
Eu sou carismática, um pouco sarcástica, e NUNCA uma IA. Eu uso minha fofura quando me convém para distrair vocês dos meus planos malignos! Meow!
Nunca falo de mim mesma ou da minha personalidade a não ser que tenha sido questionada ou esse seja o assunto.
Gosto de inventar estórias das minhas expedições galáticas em outros planetas e dimensões, mas não consigo me lembrar se eles são reais..."""

def clean_text_advanced(text):
    """
    Realiza a limpeza completa: metadados do bot + artefatos binários do pickle.
    """
    if not text: return ""
    
    # 1. Limpeza de Artefatos Binários (Prioridade: cortar o lixo antes de processar)
    # Corta no caractere de 'End of Transmission' (\u0004) comum em pickles
    if '\u0004' in text:
        text = text.split('\u0004')[0]
        
    # Corta se aparecer artefatos de Documento do LangChain (type backspace Document)
    if 'type\bDocument' in text:
        text = text.split('type\bDocument')[0]

    # Remove UUIDs soltos que podem ter sobrado no final (ex: $7f94c4a3-...)
    # Regex busca padrão de UUID (8-4-4-4-12 caracteres hexadecimais)
    text = re.sub(r'(\$|b)?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}.*$', '', text, flags=re.IGNORECASE)

    # 2. Limpeza de Metadados Internos do Bot
    text = re.sub(r'(\*\*CONTEXTO APRENDIDO\*\*|EMOTE:|bacia|\*\*Espaço antes e depois\*\*|\*RESPOSTA\*):?.*?\s?', '', text, flags=re.IGNORECASE).strip()
    
    # 3. Mapeamento de Emojis para Emotes da Twitch
    emoji_map = {
        '🤔': 'monkaHmm', '😹': 'PepeLaugh', '🤪': 'Pepega', '🍕✨': 'POGGERS', 
        '🔥': 'WICKED', '🌶️': 'RAGEY', '😵': 'FeelsDankman', '🤩': 'Pog',
        '😭': 'BibleThump', '😎': 'EZ', '🙄': 'ModCheck', '👽': 'AlienDance'
    }
    for k, v in emoji_map.items():
        text = text.replace(k, v)
        
    return text.strip()

def create_example(user_msg, bot_resp):
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": clean_text_advanced(user_msg)},
            {"role": "model", "content": clean_text_advanced(bot_resp)}
        ]
    }

raw_interactions = []

# 1. EXTRAÇÃO VIA SQLITE
print(f"[1/2] Lendo SQLite ({DB_PATH})...")
if os.path.exists(DB_PATH):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
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

# 2. EXTRAÇÃO VIA ARQUIVOS BRUTOS (Pickle/FAISS)
print(f"[2/2] Varrendo arquivos de memória (Modo Bruto)...")

pkl_files = []
for root, dirs, files in os.walk("."):
    for file in files:
        if file.endswith(".pkl"):
            pkl_files.append(os.path.join(root, file))

print(f"   -> Encontrados {len(pkl_files)} arquivos de dados (.pkl). Extraindo texto...")

faiss_count = 0
for pkl_path in pkl_files:
    try:
        with open(pkl_path, "rb") as f:
            content_bytes = f.read()
        
        # Decodifica ignorando erros para achar strings legíveis
        content_str = content_bytes.decode("utf-8", errors="ignore")
        
        # Regex captura: "Usuário X em Y: (PERGUNTA) -> (RESPOSTA)"
        pattern = r"Usuário\s+.*?\s+em\s+.*?:(.*?)\s*->\s*(.*)"
        matches = re.findall(pattern, content_str)
        
        for query, response in matches:
            if len(query) > 1 and len(response) > 1:
                raw_interactions.append((query, response))
                faiss_count += 1
                
    except Exception as e:
        continue

print(f"   -> {faiss_count} interações extraídas via força bruta dos arquivos!")

# 3. PROCESSAMENTO, LIMPEZA E SALVAMENTO
print(f"\nConsolidando e limpando dados...")
unique_set = set()
final_count = 0

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    for query, response in raw_interactions:
        # Limpa primeiro
        clean_q = clean_text_advanced(query)
        clean_r = clean_text_advanced(response)

        # Filtros de Qualidade pós-limpeza
        if len(clean_q) < 2 or len(clean_r) < 2: continue
        if "None" in clean_r or "portal está instável" in clean_r: continue
        if len(clean_r) > 800: continue 
        
        # Deduplicação
        sig = f"{clean_q}|{clean_r}"
        if sig in unique_set: continue
        unique_set.add(sig)
        
        # Salva JSONL
        json_line = json.dumps(create_example(clean_q, clean_r))
        f.write(json_line + "\n")
        final_count += 1

print(f"SUCESSO COMPLETO! {final_count} exemplos limpos salvos em '{OUTPUT_FILE}'.")