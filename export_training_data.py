import json
import sqlite3
import os
import re
from datetime import datetime
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS

def _clean_completion(text):
    """
    Normaliza a string de 'completion' removendo lixo de roleplay,
    instruções literais e substituindo emojis por emotes de texto válidos.
    """
    if not text:
        return ""
    
    # Remove tags de contexto, espaçamento literal e instruções que o modelo repetiu
    text = re.sub(r'(\*\*CONTEXTO APRENDIDO\*\*|EMOTE:|bacia|\*\*Espaço antes e depois\*\*|\*RESPOSTA\*):?.*?\s?', '', text, flags=re.IGNORECASE).strip()
    
    # Remove todo texto dentro de asteriscos, exceto *glitch*
    # text = re.sub(r'\*([^*]+)\*', r'', text, flags=re.IGNORECASE).strip()
    
    # Mapeamento para garantir que o modelo aprenda a usar os emotes de texto da lista
    emoji_map = {
        '🤔': 'monkaHmm', 
        '😹': 'PepeLaugh', 
        '🤪': 'Pepega', 
        '🍕✨': 'POGGERS', 
        '🔥': 'WICKED', 
        '🌶️': 'RAGEY', 
        '😵': 'FeelsDankman', 
        '🤩': 'Pog', 
        '💖': 'Kissahomie', 
        '✨': 'Pog',
        '🤫': 'monkaHmm',
        '❤️': 'Kissahomie',
        '😳': 'peepoShy'
    }
    for emoji, replacement in emoji_map.items():
        # Adiciona espaços para garantir que o emote não cole na palavra adjacente
        text = text.replace(emoji, f" {replacement} ")

    # LIMPEZA DE ESPAÇOS E PONTUAÇÃO EXCESSIVA
    text = re.sub(r'\s{2,}', ' ', text).strip() # Múltiplos espaços para um
    text = re.sub(r'\s*([.,!?])', r'\1', text).strip() # Remove espaço antes de pontuação
    
    # Remove lixo de texto que o modelo inventou
    # text = text.replace("só que...", "só que").strip()
    
    return text

db_path = "glorpinia_memory.db"
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
output_file = f"exported_memory_cleaned_{timestamp}.jsonl"

embeddings_model = "sentence-transformers/all-MiniLM-L6-v2"

# Carrega embeddings
embeddings = HuggingFaceEmbeddings(model_name=embeddings_model)

# Conecta ao DB e pega todos os registros
conn = sqlite3.connect(db_path)
c = conn.cursor()
c.execute("SELECT channel, user, vectorstore_path FROM memories")
rows = c.fetchall()
conn.close()

data = []
for channel, user, path in rows:
    try:
        # Carrega o FAISS específico do user/channel
        if path and os.path.exists(path):
            vectorstore = FAISS.load_local(path, embeddings, allow_dangerous_deserialization=True)
            
            # Extrai TODOS os docs
            docs = vectorstore.docstore._dict.values()
            
            for doc in docs:
                # Parse do formato salvo: "Usuário {user} em {channel}: {query} -> {response}"
                if " -> " in doc.page_content:
                    full_str = doc.page_content
                    # Certifique-se de que a separação por ": " lida com casos onde o username tem ": "
                    parts = full_str.split(" -> ", 1)
                    query_response_part = parts[0].split(": ", 1)[1] if ": " in parts[0] else parts[0]
                    response_part = parts[1]
                    
                    query_part = query_response_part
                    
                    # Limpa e formata a Completion (Resposta)
                    cleaned_completion = _clean_completion(response_part)
                    
                    # Limpa e formata o Prompt (Pergunta)
                    prompt = f"Como Glorpinia, responda a este chat: @, {query_part.strip()}"

                    # Filtra: Ignora fallbacks curtos ou vazios pra qualidade
                    if len(cleaned_completion) > 10 and "glorp deu ruim" not in cleaned_completion.lower():
                        data.append({
                            "prompt": prompt,
                            "completion": cleaned_completion,
                            "metadata": {
                                "user": user.replace("user123", "UserAnon"),
                                "channel": channel,
                                "timestamp": str(datetime.now())
                            }
                        })
        else:
            print(f"[WARNING] Arquivo FAISS não encontrado: {path}")
    except Exception as e:
        print(f"[ERROR] Falha ao carregar {path}: {e}")

# Salva pro JSONL
with open(output_file, "w", encoding="utf-8") as f:
    for item in data:
        f.write(json.dumps(item) + "\n")

print(f"Exportado {len(data)} amostras limpas para {output_file}!")
if data:
    print("Exemplo da primeira (LIMPA):")
    print(json.dumps(data[0], indent=2))