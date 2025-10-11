import sqlite3
import os
from datetime import datetime
import logging

# Imports opcionais (langchain-huggingface / langchain-community podem ter nomes/versões diferentes)
try:
    from langchain_huggingface import HuggingFaceEmbeddings
except Exception:
    HuggingFaceEmbeddings = None

try:
    from langchain_community.vectorstores import FAISS
except Exception:
    FAISS = None

class MemoryManager:
    def __init__(self, db_path="glorpinia_memory.db"):
        self.db_path = db_path
        if HuggingFaceEmbeddings is None:
            logging.error("langchain_huggingface não disponível. Instale 'langchain-huggingface' ou verifique a versão.")
            raise ImportError("HuggingFaceEmbeddings não disponível — instale 'langchain-huggingface'.")

        self.embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
        self.vectorstore = None  # Será setado por load_user_memory
        self.init_memory_db()

    def init_memory_db(self):
        """Inicializa o DB SQLite com tabela de memórias."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS memories
                     (channel TEXT, user TEXT, vectorstore_path TEXT, last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        conn.commit()
        conn.close()

    def load_user_memory(self, channel, user):
        """Carrega memória long-term (FAISS) específica do user/channel do DB."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT vectorstore_path FROM memories WHERE channel=? AND user=?", (channel, user))
        result = c.fetchone()
        conn.close()
        
        if result:
            path = result[0]
            if os.path.exists(path):
                self.vectorstore = FAISS.load_local(
                    path, 
                    self.embeddings, 
                    allow_dangerous_deserialization=True
                )
                print(f"[DEBUG] Memória carregada de {path}")
            else:
                print(f"[WARNING] Arquivo FAISS não encontrado: {path}")
                self.vectorstore = None
        else:
            print(f"[DEBUG] Nenhuma memória encontrada para {user} em {channel}")
            self.vectorstore = None

    def save_user_memory(self, channel, user, query, response):
        """Salva nova interação (query -> response) na memória long-term (FAISS + DB)."""
        # Cria doc no formato salvo
        doc = f"Usuário {user} em {channel}: {query} -> {response}"
        
        # Adiciona ao vectorstore (cria se não existir)
        if self.vectorstore is None:
            self.vectorstore = FAISS.from_texts([doc], self.embeddings)
        else:
            self.vectorstore.add_texts([doc])
        
        # Path único por user/channel
        path = f"memory_{channel}_{user}.faiss"
        self.vectorstore.save_local(path)
        
        # Atualiza DB
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO memories (channel, user, vectorstore_path, last_updated) VALUES (?, ?, ?, ?)",
                  (channel, user, path, datetime.now()))
        conn.commit()
        conn.close()
        
        print(f"[DEBUG] Memória salva em {path}")