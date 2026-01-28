import os
import sqlite3
import logging
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import FAISS
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

def migrate_memories():
    db_path = "glorpinia_memory.db"
    
    if not os.path.exists(db_path):
        logging.error("Banco de dados não encontrado. Nada para migrar.")
        return

    try:
        new_embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")
        logging.info("Novo modelo (text-embedding-004) inicializado.")
    except Exception as e:
        logging.error(f"Erro ao iniciar API do Google: {e}")
        return

    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    try:
        c.execute("SELECT vectorstore_path FROM memories")
        rows = c.fetchall()
    except Exception as e:
        logging.error(f"Erro ao ler banco de dados: {e}")
        return
    conn.close()

    logging.info(f"Encontrados {len(rows)} arquivos de memória para migrar...")

    success_count = 0
    
    for row in rows:
        path = row[0]
        if not os.path.exists(path):
            logging.warning(f"Arquivo não encontrado (pulando): {path}")
            continue

        logging.info(f"Migrando: {path}...")

        try:
            old_vectorstore = FAISS.load_local(
                path, 
                embeddings=None, 
                allow_dangerous_deserialization=True
            )

            raw_docs = list(old_vectorstore.docstore._dict.values())
            texts = [doc.page_content for doc in raw_docs]
            
            if not texts:
                logging.warning(f"Arquivo vazio ou sem texto recuperável: {path}")
                continue

            logging.info(f"  -> Re-processando {len(texts)} memórias com o novo modelo...")

            new_vectorstore = FAISS.from_texts(texts, new_embeddings)

            new_vectorstore.save_local(path)
            
            success_count += 1
            logging.info(f"  -> Sucesso! {path} atualizado.")

        except Exception as e:
            logging.error(f"  -> Falha ao migrar {path}: {e}")

    logging.info(f"Migração concluída! {success_count}/{len(rows)} arquivos atualizados.")

if __name__ == "__main__":
    print("--- INICIANDO MIGRAÇÃO DE MEMÓRIA ---")
    print("Isso pode levar alguns minutos dependendo do tamanho do histórico.")
    migrate_memories()