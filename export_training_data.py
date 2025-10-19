import json
import sqlite3
import os
from datetime import datetime
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS

# Configs
db_path = "glorpinia_memory.db"
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
output_file = f"exported_memory_{timestamp}.jsonl"

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
                    query_part = full_str.split(" -> ")[0].split(": ", 1)[1] if ": " in full_str else full_str
                    response_part = full_str.split(" -> ")[1]
                    
                    # Limpa e formata
                    prompt = f"Como Glorpinia, responda: {query_part.strip()}"
                    completion = response_part.strip()
                    
                    # Filtra: Ignora fallbacks curtos ou vazios pra qualidade
                    if len(completion) > 10 and "glorp deu ruim" not in completion.lower():
                        data.append({
                            "prompt": prompt,
                            "completion": completion,
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

print(f"Exportado {len(data)} amostras reais para {output_file}!")
if data:
    print("Exemplo da primeira:")
    print(json.dumps(data[0], indent=2, ensure_ascii=False))