import logging
import os
import sqlite3
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s:%(levelname)s:%(name)s:%(message)s")

# Importa a biblioteca de embedding da Google
try:
    from langchain_google_genai import GoogleGenerativeAIEmbeddings
except ImportError:
    GoogleGenerativeAIEmbeddings = None
    logging.warning("langchain-google-genai nao encontrado. O RAG sera desabilitado. Instale 'langchain-google-genai'.")

try:
    from langchain_community.vectorstores import FAISS
except ImportError:
    FAISS = None
    logging.warning("FAISS nao encontrado. O RAG sera desabilitado. Instale 'langchain-community'.")


class MemoryManager:
    """
    Gerencia a memoria de longo prazo (RAG) da Glorpinia usando FAISS (para vetores)
    e SQLite (para metadata e fallback).
    """

    def __init__(self, db_path="glorpinia_memory.db"):
        self.db_path = db_path
        self.embeddings = None
        self._vectorstores = {}
        self._active_memory_key = None
        self._use_faiss = False

        # Cria a estrutura do DB na inicialização
        self._initialize_db()

        force_sqlite = os.environ.get("GLORPINIA_FORCE_SQLITE") == "1"

        # Verifica se as bibliotecas (Google + FAISS) estão prontas
        if not force_sqlite and GoogleGenerativeAIEmbeddings is not None and FAISS is not None:
            try:
                # Usa o embedding da Google, que usa a mesma API_KEY do .env
                self.embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")
                self._use_faiss = True
                logging.info("[GLORP-MEMORY] FAISS/RAG ATIVADO (usando Google Embeddings).")
            except Exception as e:
                logging.error(f"[GLORP-MEMORY] Falha ao carregar GoogleGenerativeAIEmbeddings (RAG desativado): {e}")
                self._use_faiss = False

        if not self._use_faiss:
            logging.warning("[GLORP-MEMORY] RAG DESATIVADO. Usando SQLite apenas como fallback de log.")

    def _initialize_db(self):
        """Cria as tabelas necessarias no SQLite se elas nao existirem."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        c.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
                channel TEXT NOT NULL,
                user TEXT NOT NULL,
                vectorstore_path TEXT,
                last_updated TEXT,
                PRIMARY KEY (channel, user)
            )
        """
        )

        c.execute(
            """
            CREATE TABLE IF NOT EXISTS interactions (
                channel TEXT,
                user TEXT,
                query TEXT,
                response TEXT,
                ts TEXT
            )
        """
        )
        conn.commit()
        conn.close()

    def _memory_key(self, channel, user):
        return (channel, user)

    def _memory_path(self, channel, user):
        return f"memory_{channel}_{user}.faiss"

    def _fetch_vectorstore_path(self, channel, user):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT vectorstore_path FROM memories WHERE channel=? AND user=?", (channel, user))
        row = c.fetchone()
        conn.close()
        if not row:
            return None
        return row[0]

    def load_user_memory(self, channel, user):
        """Carrega o vectorstore (FAISS) para um user/channel especifico."""
        key = self._memory_key(channel, user)
        self._active_memory_key = key

        if not self._use_faiss:
            return None

        if key in self._vectorstores:
            return self._vectorstores[key]

        vectorstore_path = self._fetch_vectorstore_path(channel, user)
        if vectorstore_path and os.path.exists(vectorstore_path):
            try:
                self._vectorstores[key] = FAISS.load_local(
                    vectorstore_path, self.embeddings, allow_dangerous_deserialization=True
                )
                logging.debug(f"[GLORP-MEMORY] FAISS loaded for {user} in {channel}")
            except Exception as e:
                logging.error(f"[GLORP-MEMORY] Erro ao carregar FAISS para {user} em {channel}: {e}")
                self._vectorstores.pop(key, None)
        else:
            self._vectorstores.pop(key, None)
            logging.debug(f"[GLORP-MEMORY] No FAISS found for {user} in {channel}. Starting fresh.")

        return self._vectorstores.get(key)

    def save_user_memory(self, channel, user, query, response):
        """Salva nova interação (query -> response) na memória long-term (FAISS + DB)."""

        if not self._use_faiss:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute(
                "INSERT INTO interactions (channel, user, query, response, ts) VALUES (?, ?, ?, ?, ?)",
                (channel, user, query, response, datetime.now()),
            )
            conn.commit()
            conn.close()
            logging.debug(f"[GLORP-MEMORY] Interaction saved to SQLite fallback for {user} in {channel}")
            return

        key = self._memory_key(channel, user)
        self._active_memory_key = key
        vectorstore = self.load_user_memory(channel, user)
        doc = f"Usuário {user} em {channel}: {query} -> {response}"

        if vectorstore is None:
            vectorstore = FAISS.from_texts([doc], self.embeddings)
            self._vectorstores[key] = vectorstore
        else:
            vectorstore.add_texts([doc])

        path = self._memory_path(channel, user)
        vectorstore.save_local(path)

        logging.info(f"[GLORP-MEMORY] Interaction saved and FAISS updated for {user} in {channel}")

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO memories (channel, user, vectorstore_path, last_updated) VALUES (?, ?, ?, ?)",
            (channel, user, path, datetime.now()),
        )
        conn.commit()
        conn.close()

    def search_memory(self, channel, user, query, k=3):
        """
        Busca memórias relevantes no banco vetorial (RAG).
        Retorna uma string formatada com as memórias encontradas.
        """
        if not self._use_faiss:
            return ""

        key = self._memory_key(channel, user)
        vectorstore = self._vectorstores.get(key)
        if vectorstore is None:
            vectorstore = self.load_user_memory(channel, user)

        if vectorstore is None:
            return ""

        try:
            docs = vectorstore.similarity_search(query, k=k)
            if not docs:
                return ""

            return "\n".join([f"- {doc.page_content}" for doc in docs])
        except Exception as e:
            logging.error(f"[GLORP-MEMORY] Erro na busca vetorial: {e}")
            return ""

    @property
    def vectorstore(self):
        """Compatibilidade com clientes antigos: retorna o vectorstore ativo."""
        if not self._active_memory_key:
            return None
        return self._vectorstores.get(self._active_memory_key)

    @vectorstore.setter
    def vectorstore(self, value):
        """Compatibilidade com clientes antigos: escreve no vectorstore ativo."""
        if self._active_memory_key is None:
            self._active_memory_key = ("__default__", "__default__")
        self._vectorstores[self._active_memory_key] = value
