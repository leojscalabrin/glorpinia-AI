import json
import sqlite3
from datetime import datetime

db_path = "glorpinia_memory.db"
output_file = "training_data.jsonl"

conn = sqlite3.connect(db_path)
c = conn.cursor()
c.execute("SELECT channel, user, vectorstore_path FROM memories")
rows = c.fetchall()
conn.close()

data = []
for channel, user, path in rows:
    # Simula extração de docs do FAISS (ajuste se precisar carregar real)
    # Para demo: assume docs como "query -> response"
    doc = f"Exemplo: Usuário {user} em {channel}: olá -> glorp meow!"  # Substitua por real parse do .faiss
    data.append({
        "prompt": "Como Glorpinia, responda: olá",
        "completion": "glorp meow!",
        "metadata": {"user": user, "channel": channel, "timestamp": str(datetime.now())}
    })

with open(output_file, "w", encoding="utf-8") as f:
    for item in data:
        f.write(json.dumps(item) + "\n")

print(f"Exportado {len(data)} amostras para {output_file}. Use como dataset!")