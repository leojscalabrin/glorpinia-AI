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
        # Default state: do not instantiate heavy embedding/FAISS objects at
        # startup. Attempt creation lazily only when needed. Provide an env
        # override GLORPINIA_FORCE_SQLITE=1 to force the lightweight fallback.
        self.embeddings = None
        self.vectorstore = None
        self._use_faiss = False
        force_sqlite = os.environ.get('GLORPINIA_FORCE_SQLITE') == '1'
        if not force_sqlite and HuggingFaceEmbeddings is not None and FAISS is not None:
            # Try to instantiate embeddings lazily but guard against heavy
            # imports failing (e.g., sentence-transformers importing transformers.trainer).
            try:
                self.embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
                self._use_faiss = True
                self.vectorstore = None  # Will be set by load_user_memory
                logging.info("Initialized HuggingFaceEmbeddings for MemoryManager.")
            except Exception as e:
                logging.warning(f"Failed to initialize HuggingFaceEmbeddings: {e}. Falling back to SQLite-only memory.")
                self.embeddings = None
                self.vectorstore = None
                self._use_faiss = False
        else:
            if force_sqlite:
                logging.info("GLORPINIA_FORCE_SQLITE=1 — using SQLite-only memory fallback.")
            else:
                logging.warning("HuggingFaceEmbeddings or FAISS not available — using SQLite-only fallback memory manager.")

        # Initialize the SQLite DB for interactions/metadata regardless of path
        self.init_memory_db()

    def init_memory_db(self):
        """Inicializa o DB SQLite com tabela de memórias."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        # Table for vectorstore metadata (when using FAISS)
        c.execute('''CREATE TABLE IF NOT EXISTS memories
                     (channel TEXT, user TEXT, vectorstore_path TEXT, last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        # Fallback table for simple interaction storage (plain text)
        c.execute('''CREATE TABLE IF NOT EXISTS interactions
                     (channel TEXT, user TEXT, query TEXT, response TEXT, ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        conn.commit()
        conn.close()

    def load_user_memory(self, channel, user):
        """Carrega memória long-term (FAISS) específica do user/channel do DB."""
        if not self._use_faiss:
            # No FAISS available — leave vectorstore as None
            print(f"[DEBUG] FAISS not available — skipping vectorstore load for {user} in {channel}")
            self.vectorstore = None
            return

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
        if not self._use_faiss:
            # Fallback: store the raw interaction in the interactions table
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("INSERT INTO interactions (channel, user, query, response, ts) VALUES (?, ?, ?, ?, ?)",
                      (channel, user, query, response, datetime.now()))
            conn.commit()
            conn.close()
            print(f"[DEBUG] Interaction saved to SQLite fallback for {user} in {channel}")
            return

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