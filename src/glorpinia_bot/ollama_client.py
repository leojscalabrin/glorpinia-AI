import os
import requests
import re
import logging

# Imports para compatibilidade com o MemoryManager (LangChain/SQLite/FAISS)
try:
    from langchain.schema import HumanMessage, AIMessage
except ImportError:
    # Fallback se a LangChain não estiver instalada
    class HumanMessage:
        def __init__(self, content): self.content = content
    class AIMessage:
        def __init__(self, content): self.content = content

try:
    from .memory_manager import MemoryManager
except ImportError:
    logging.warning("O MemoryManager não foi encontrado. O bot não terá memória de longo prazo.")
    # Se for estritamente necessário um placeholder para rodar
    class MemoryManager:
        def load_user_memory(self, *args): pass
        def save_user_memory(self, *args): pass
        @property
        def vectorstore(self): return None


# Configuração da URL base do Ollama, lendo de variáveis de ambiente
OLLAMA_URL = os.getenv("OLLAMA_API_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL_NAME", "glorpinia")

class OllamaClient:
    """
    Cliente para interagir com o modelo Glorpinia customizado no servidor Ollama.
    """
    def __init__(self, personality_profile):
        self.personality_profile = personality_profile
        self.memory = None 

    def get_response(self, query, channel, author, memory_mgr: 'MemoryManager'):
        """
        Gera uma resposta usando a API de chat do Ollama, injetando RAG como contexto.
        """
        if not OLLAMA_MODEL or not OLLAMA_URL:
            logging.error("Variáveis de ambiente OLLAMA_MODEL_NAME ou OLLAMA_API_URL não definidas.")
            return f"@{author}, Erro de configuração glorp O portal de Ollama está offline. RIPBOZO"

        memory_mgr.load_user_memory(channel, author)
        vectorstore = memory_mgr.vectorstore
        
        # Recuperação de Contexto (RAG/Memória de Longo Prazo)
        long_term_context = ""
        if vectorstore:
            try:
                # O retriever busca interações passadas relevantes
                retriever = vectorstore.as_retriever(search_kwargs={"k": 3})
                docs = retriever.invoke(query)
                
                if docs:
                    # Formata as interações passadas em um bloco de CONTEXTO APRENDIDO
                    long_term_context = "\n".join([doc.page_content for doc in docs])
                    long_term_context = f"**CONTEXTO APRENDIDO (MEMÓRIA GLORPINIA):** {long_term_context}"
            except Exception as e:
                logging.error(f"[RAG ERROR] Falha ao buscar contexto: {e}")

        # Montagem do System Prompt (Reforço do RAG)
        system_prompt = f'''
        Você é Glorpinia. Sua personalidade está definida no seu sistema.
        Use o seguinte **CONTEXTO APRENDIDO** para enriquecer sua resposta se for relevante.
        Lembre-se da REGRA CRÍTICA DE EMOTES (espaço antes e depois).
        '''

        # Montagem da Mensagem no formato da API Ollama
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"{long_term_context}\n\nQuery do Usuário: {query}"}
        ]
        
        payload = {
            "model": OLLAMA_MODEL,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": 0.7, 
                "num_ctx": 4096 # Garante espaço suficiente para o RAG
            }
        }
        
        # Chamada à API do Ollama
        try:
            response = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=30)
            response.raise_for_status() # Lança exceção para códigos 4xx/5xx
            data = response.json()
            
            generated = data['message']['content'].strip()
            
        except requests.exceptions.RequestException as e:
            logging.error(f"[ERROR] Falha na comunicação com Ollama API: {e}")
            generated = "glorp-glorp. O portal está instável. Eu não consigo me comunicar. Sadge"

        # Limpeza Final e Salvamento de Memória
        generated = self._clean_response(generated)

        if generated and generated != "glorp-glorp. O portal está instável. Eu não consigo me comunicar. Sadge":
            # Salva a interação query/response na memória de longo prazo (RAG)
            memory_mgr.save_user_memory(channel, author, query, generated)
            
            final_response = f"@{author}, {generated}"
            return final_response
        else:
            fallback = "Meow. O portal de Glorp está com lag. Tente novamente! 😸"
            final_fallback = f"@{author}, {fallback}"
            return final_fallback

    def _clean_response(self, generated):
        generated = generated.strip()
        
        generated = re.sub(r'\*([A-Za-z0-9]+)\*', r'\1', generated)
        
        generated = generated.replace(" espaco ", " ").strip()
        generated = generated.replace(" espaco", " ").strip()
        generated = generated.replace("espaco ", " ").strip()
        generated = generated.replace("*EMOTE*:", "").strip() # Remove este lixo de template
        generated = generated.replace("bacia", "Kissahomie").strip() # Limpa a literal

        generated = re.sub(r'\[/INST\]', '', generated).strip()
        generated = re.sub(r'<\|eot_id\|>', '', generated).strip()

        return generated