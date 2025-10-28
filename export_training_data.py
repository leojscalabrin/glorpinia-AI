import json
import sqlite3
import os
from datetime import datetime

try:
    from langchain_huggingface import HuggingFaceEmbeddings
    from langchain_community.vectorstores import FAISS
except ImportError:
    print("[ERROR] Nao foi possivel importar LangChain RAG components. Verifique as dependencias.")
    exit(1)


# Configs
db_path = "glorpinia_memory.db"
# Gera um arquivo com timestamp para nao sobrescrever
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S") 
output_file = f"exported_memory_{timestamp}.jsonl"
embeddings_model = "sentence-transformers/all-MiniLM-L6-v2"

# Carrega embeddings (necessario para instanciar o FAISS corretamente)
try:
    embeddings = HuggingFaceEmbeddings(model_name=embeddings_model)
except Exception as e:
    print(f"[ERROR] Falha ao carregar embeddings: {e}. Verifique se as dependencias estao instaladas (ex: torch, transformers).")
    exit(1)


# Conecta ao DB e pega todos os registros de memória FAISS
conn = sqlite3.connect(db_path)
c = conn.cursor()
c.execute("SELECT channel, user, vectorstore_path FROM memories")
rows = c.fetchall()
conn.close()

data = []
for channel, user, path in rows:
    # Ignora users genericos que podem ser lixo
    if user.lower() in ["system", "system_prompt", "anon"]:
        continue
        
    try:
        # Carrega o FAISS específico do user/channel
        if path and os.path.exists(path):
            # allow_dangerous_deserialization=True e NECESSARIO
            vectorstore = FAISS.load_local(path, embeddings, allow_dangerous_deserialization=True)
            
            # Extrai TODOS os docs
            # Em versoes mais recentes do LangChain, docstore pode ser privado (pode quebrar)
            docs = vectorstore.docstore._dict.values()
            
            for doc in docs:
                # Parse do formato salvo: "Usuário {user} em {channel}: {query} -> {response}"
                if " -> " in doc.page_content:
                    full_str = doc.page_content
                    # Separa query e response
                    query_part = full_str.split(" -> ")[0].split(": ", 1)[-1] # Pega o que vem depois do último ":"
                    response_part = full_str.split(" -> ", 1)[1] # Pega o que vem depois do primeiro " -> "
                    
                    # Formata no formato JSONL (prompt/completion)
                    prompt = f"Como Glorpinia, responda a este chat: {query_part.strip()}"
                    completion = response_part.strip()
                    
                    # Filtra: Ignora fallbacks curtos ou vazios pra qualidade
                    if len(completion) > 10 and "glorp deu ruim" not in completion.lower() and "meow. glorp-glorp." not in completion.lower():
                        data.append({
                            "prompt": prompt,
                            "completion": completion,
                            "metadata": {
                                "user": user,
                                "channel": channel,
                                "timestamp": str(datetime.now())
                            }
                        })
        else:
            print(f"[WARNING] Arquivo FAISS não encontrado: {path} para {user}/{channel}")
    except Exception as e:
        print(f"[ERROR] Falha ao carregar {path}: {e}")

# Salva pro JSONL
with open(output_file, "w", encoding="utf-8") as f:
    for item in data:
        # Use ensure_ascii=False para manter acentos e caracteres especiais
        f.write(json.dumps(item, ensure_ascii=False) + "\n")

print("-" * 50)
print(f"Exportado {len(data)} amostras reais para {output_file}!")
if data:
    print("Exemplo da primeira amostra (para conferencia de formato):")
    print(json.dumps(data[0], indent=2, ensure_ascii=False))
print("-" * 50)