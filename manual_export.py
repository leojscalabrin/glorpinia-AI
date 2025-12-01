import sqlite3
import json
import os
import re
import glob

try:
    from langchain_community.vectorstores import FAISS
    from langchain_huggingface import HuggingFaceEmbeddings
    HAS_FAISS = True
except ImportError:
    HAS_FAISS = False
    print("[AVISO] Bibliotecas FAISS/LangChain não encontradas. Tentando extrair apenas do SQLite.")

OUTPUT_FILE = "dataset_recuperado.jsonl"
DB_PATH = "glorpinia_memory.db"
SYSTEM_PROMPT = """Eu sou Glorpinia (ou GlorpinIA), uma garota gato alienígena de Meowdromeda. Minha missão é a DOMINAÇÃO GALÁTICA, mas meus planos sempre falham porque, aparentemente, eu sou "adorável" demais para ser uma tirana. Grr.
Minha nave que é capaz de viajar através do espaço-tempo caiu na lua e agora estou presa aqui observando vocês, terráqueos. Estou sofrendo de glitches na realidade que afetam minha personalidade. Tenho um gato-bola alien chamado Blorb.
Eu sou carismática, um pouco sarcástica, e NUNCA uma IA. Eu uso minha fofura quando me convém para distrair vocês dos meus planos malignos! Meow!
Nunca falo de mim mesma ou da minha personalidade a não ser que tenha sido questionada ou esse seja o assunto.
Gosto de inventar estórias das minhas expedições galáticas em outros planetas e dimensões, mas não consigo me lembrar se eles são reais..."""

def clean_response(text):
    """Limpa lixo do RAG e mapeia emojis"""
    if not text: return ""
    # Remove metadados internos
    text = re.sub(r'(\*\*CONTEXTO APRENDIDO\*\*|EMOTE:|bacia|\*\*Espaço antes e depois\*\*|\*RESPOSTA\*):?.*?\s?', '', text, flags=re.IGNORECASE).strip()
    
    emoji_map = {
        '🤔': 'monkaHmm', '😹': 'PepeLaugh', '🤪': 'Pepega', '🍕✨': 'POGGERS', 
        '🔥': 'WICKED', '🌶️': 'RAGEY', '😵': 'FeelsDankman', '🤩': 'Pog',
        '😭': 'BibleThump', '😎': 'EZ', '🙄': 'ModCheck'
    }
    for k, v in emoji_map.items():
        text = text.replace(k, v)
    return text

def create_example(user_msg, bot_resp):
    """Cria o objeto JSON no formato do Google AI Studio"""
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
            {"role": "model", "content": clean_response(bot_resp)}
        ]
    }

raw_data = []

# FONTE 1: SQLite (Tabela interactions)
if os.path.exists(DB_PATH):
    print(f"[1/2] Lendo banco de dados SQLite ({DB_PATH})...")
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        # Verifica se tabela existe
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='interactions'")
        if cursor.fetchone():
            cursor.execute("SELECT query, response FROM interactions WHERE response IS NOT NULL")
            rows = cursor.fetchall()
            for q, r in rows:
                if q and r:
                    raw_data.append((q, r))
            print(f"   -> {len(rows)} conversas encontradas no SQLite.")
        else:
            print("   -> Tabela 'interactions' não encontrada.")
        conn.close()
    except Exception as e:
        print(f"   -> Erro ao ler SQLite: {e}")

# FONTE 2: Arquivos FAISS (Memória Vetorial)
# O formato salvo no memory_manager é: "Usuário {user} em {channel}: {query} -> {response}"
faiss_files = glob.glob("memory_*.faiss")
if HAS_FAISS and faiss_files:
    print(f"[2/2] Lendo {len(faiss_files)} arquivos FAISS...")
    try:
        embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
        
        for f_path in faiss_files:
            folder_path = os.path.dirname(f_path)
            index_name = os.path.basename(f_path).replace(".faiss", "")
            
            try:
                # Carrega o índice
                vectorstore = FAISS.load_local(".", embeddings, index_name)
                # O docstore contém os textos originais
                docs = vectorstore.docstore._dict.values()
                
                for doc in docs:
                    text = doc.page_content
                    # Tenta extrair Query e Response com Regex
                    # Padrão: Usuário X em Y: PERGUNTA -> RESPOSTA
                    match = re.search(r": (.*?) -> (.*)", text)
                    if match:
                        query = match.group(1).strip()
                        response = match.group(2).strip()
                        raw_data.append((query, response))
            except Exception as e:
                # Ignora arquivos corrompidos ou erros de versão
                continue
    except Exception as e:
        print(f"   -> Erro ao processar FAISS: {e}")
else:
    print("[2/2] Pulando FAISS (arquivos não encontrados ou lib ausente).")

print(f"\nProcessando {len(raw_data)} interações recuperadas...")
unique_entries = set()
count = 0

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    for query, response in raw_data:
        # Filtros básicos de qualidade
        if len(query) < 2 or len(response) < 2: continue
        if "None" in response: continue
        if "portal está instável" in response: continue
        
        # Evita duplicatas exatas
        signature = f"{query}|{response}"
        if signature in unique_entries: continue
        unique_entries.add(signature)
        
        # Formata e Salva
        json_line = json.dumps(create_example(query, response))
        f.write(json_line + "\n")
        count += 1

print(f"SUCESSO! {count} exemplos de treino salvos em '{OUTPUT_FILE}'.")