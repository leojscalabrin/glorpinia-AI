import sqlite3
import os
from datetime import datetime
import logging

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
        self.vectorstore = None
        self._use_faiss = False
        
        # Cria a estrutura do DB na inicialização
        self._initialize_db()

        force_sqlite = os.environ.get('GLORPINIA_FORCE_SQLITE') == '1'
        
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
        
        self.vectorstore = None # Sera carregado de forma lazy em load_user_memory

    def _initialize_db(self):
        """Cria as tabelas necessarias no SQLite se elas nao existirem."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                channel TEXT NOT NULL,
                user TEXT NOT NULL,
                vectorstore_path TEXT,
                last_updated TEXT,
                PRIMARY KEY (channel, user)
            )
        """)
        
        c.execute("""
            CREATE TABLE IF NOT EXISTS interactions (
                channel TEXT,
                user TEXT,
                query TEXT,
                response TEXT,
                ts TEXT
            )
        """)
        conn.commit()
        conn.close()

    def load_user_memory(self, channel, user):
        """Carrega o vectorstore (FAISS) para um user/channel especifico."""
        if not self._use_faiss:
            self.vectorstore = None
            return

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT vectorstore_path FROM memories WHERE channel=? AND user=?", (channel, user))
        row = c.fetchone()
        conn.close()

        if row and row[0] and os.path.exists(row[0]):
            try:
                self.vectorstore = FAISS.load_local(
                    row[0], self.embeddings, allow_dangerous_deserialization=True
                )
                logging.debug(f"[GLORP-MEMORY] FAISS loaded for {user} in {channel}")
            except Exception as e:
                logging.error(f"[GLORP-MEMORY] Erro ao carregar FAISS para {user} em {channel}: {e}")
                self.vectorstore = None
        else:
            self.vectorstore = None
            logging.debug(f"[GLORP-MEMORY] No FAISS found for {user} in {channel}. Starting fresh.")

    def save_user_memory(self, channel, user, query, response):
        """Salva nova interação (query -> response) na memória long-term (FAISS + DB)."""
        
        if not self._use_faiss:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("INSERT INTO interactions (channel, user, query, response, ts) VALUES (?, ?, ?, ?, ?)",
                      (channel, user, query, response, datetime.now()))
            conn.commit()
            conn.close()
            logging.debug(f"[GLORP-MEMORY] Interaction saved to SQLite fallback for {user} in {channel}")
            return

        doc = f"Usuário {user} em {channel}: {query} -> {response}"

        if self.vectorstore is None:
            self.vectorstore = FAISS.from_texts([doc], self.embeddings)
        else:
            self.vectorstore.add_texts([doc])

        path = f"memory_{channel}_{user}.faiss"
        self.vectorstore.save_local(path)
        
        logging.info(f"[GLORP-MEMORY] Interaction saved and FAISS updated for {user} in {channel}")

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO memories (channel, user, vectorstore_path, last_updated) VALUES (?, ?, ?, ?)",
                  (channel, user, path, datetime.now()))
        conn.commit()
        conn.close()
    
    def search_memory(self, channel, query, k=3):
        """
        Busca memórias relevantes no banco vetorial (RAG).
        Retorna uma string formatada com as memórias encontradas.
        """
        # Se o FAISS não estiver ativo ou não houver banco carregado, retorna vazio
        if not self._use_faiss or not self.vectorstore:
            return ""

        try:
            # Busca os K documentos mais similares à pergunta atual
            docs = self.vectorstore.similarity_search(query, k=k)
            
            if not docs:
                return ""

            # Formata para ser inserido no prompt
            memory_text = "\n".join([f"- {doc.page_content}" for doc in docs])
            return memory_text

        except Exception as e:
            logging.error(f"[GLORP-MEMORY] Erro na busca vetorial: {e}")
            return ""

    @property
    def vectorstore(self):
        return self._vectorstore

    @vectorstore.setter
    def vectorstore(self, value):
        self._vectorstore = value