import os
import re
import logging
import google.generativeai as genai

from langchain_core.messages import HumanMessage, AIMessage
from .memory_manager import MemoryManager
from dotenv import load_dotenv

# Importa a ferramenta que faz a busca
from .features.search import SearchTool

load_dotenv()

try:
    genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
except Exception as e:
    logging.error(f"Falha ao configurar a API do Google GenAI: {e}")
    raise

class GeminiClient:
    """
    Cliente para interagir com o modelo Gemini, agora com
    memória de curto prazo, longo prazo (RAG) e busca na web.
    """
    def __init__(self, personality_profile):
        self.personality_profile = personality_profile
        
        self.generation_config = {
            "temperature": 0.7,
            "max_output_tokens": 1024, 
        }
        
        self.safety_settings = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ]

        self.model = genai.GenerativeModel(
            model_name="gemini-flash-latest",
            generation_config=self.generation_config,
            safety_settings=self.safety_settings,
            system_instruction=self.personality_profile 
        )
        
        # Inicializa a ferramenta de busca
        try:
            self.search_tool = SearchTool()
        except Exception as e:
            logging.error(f"[GeminiClient] Falha ao inicializar SearchTool: {e}")
            self.search_tool = None
        
        # Lista de gatilhos
        self.SEARCH_TRIGGERS = [
            'quem é', 'o que é', 'onde é', 'quando', 'notícia', 
            'aconteceu', 'resultado do jogo', 'previsão do tempo',
            'qual a previsão', 'temperatura'
        ]

    def _should_search(self, query: str) -> bool:
        """
        Decide se uma query deve ou não disparar uma busca na web.
        """
        if not self.search_tool:
            return False # Sem ferramenta de busca
            
        query_lower = query.lower()
        
        # Não busca se for um comando
        if query_lower.startswith('!'):
            return False
            
        # Busca se a query terminar com "?" E contiver um gatilho
        if query_lower.endswith('?'):
            for trigger in self.SEARCH_TRIGGERS:
                if trigger in query_lower:
                    return True
        return False

    def get_response(self, query, channel, author, memory_mgr: 'MemoryManager', recent_chat_history=None):
        """
        Gera uma resposta usando API Gemini, com memórias e busca na web.
        """
        
        # Preparar Memória de Longo Prazo (RAG)
        memory_mgr.load_user_memory(channel, author)
        vectorstore = memory_mgr.vectorstore
        long_term_context = ""
        if vectorstore:
            try:
                retriever = vectorstore.as_retriever(search_kwargs={"k": 3})
                docs = retriever.invoke(query)
                if docs:
                    long_term_context = "\n".join([doc.page_content for doc in docs])
                    long_term_context = f"**CONTEXTO APRENDIDO (MEMÓRIA GLORPINIA):**\n{long_term_context}"
            except Exception as e:
                logging.error(f"[RAG ERROR] Falha ao buscar contexto: {e}")
        
        # Preparar Memória de Curto Prazo (Histórico Recente)
        short_term_context = ""
        if recent_chat_history:
            recent_messages = list(recent_chat_history)[-10:] 
            if recent_messages:
                formatted_history = "\n".join([
                    f"{msg['author']}: {msg['content']}" for msg in recent_messages
                ])
                short_term_context = f"**HISTÓRICO RECENTE (MEMÓRIA IMEDIATA):**\n{formatted_history}"
        
        # Preparar Contexto da Web (Se necessário)
        web_context = ""
        if self._should_search(query):
            search_results = self.search_tool.perform_search(query)
            if search_results:
                web_context = f"**CONTEXTO DA INTERNET (BUSCA EM TEMPO REAL):**\n{search_results}"
        
        # Montagem do Prompt Final (Todas Memórias + Query)
        prompt = f"""
        {short_term_context}

        {long_term_context}

        {web_context}

        **Query do Usuário:** {query}
        """

        # Chamada à API do Gemini
        try:
            # Revertido para a chamada 'generate_content' simples
            response = self.model.generate_content(prompt)

            if not response.parts:
                finish_reason = "DESCONHECIDO"
                if response.candidates and response.candidates[0].finish_reason:
                     finish_reason = response.candidates[0].finish_reason.name

                logging.error(f"[ERROR] A API Gemini não retornou 'parts'. Finish Reason: {finish_reason}")
                
                if finish_reason == "SAFETY":
                    generated = "Minha resposta foi bloqueada pelos filtros de segurança. Tente reformular. Sadge."
                else:
                    generated = f"Minhas anteninhas não captaram nenhum sinal (Razão: {finish_reason}). Sadge."
            else:
                generated = response.text.strip()

        except Exception as e:
            logging.error(f"[ERROR] Falha na comunicação com a API Gemini: {e}")
            generated = "O portal está instável. Eu não consigo me comunicar. Sadge"

        # Limpeza Final e Salvamento de Memória
        generated = self._clean_response(generated)
        fallback = "Meow. O portal está com lag. Tente novamente! 😸"
        is_system_message = (author.lower() == "system")

        if generated:
            if is_system_message:
                return generated
            else:
                memory_mgr.save_user_memory(channel, author, query, generated)
                final_response = f"@{author}, {generated}"
                return final_response
        else:
            if is_system_message:
                return fallback
            else:
                final_fallback = f"@{author}, {fallback}"
                return final_fallback

    def _clean_response(self, generated):
        """Limpa a resposta dos prefixos de prompt."""
        generated = generated.strip()
        
        # Remove os novos marcadores de prompt
        generated = re.sub(r'\*\*(CONTEXTO APRENDIDO|HISTÓRICO RECENTE|CONTEXTO DA INTERNET)\*\*.*?\*RESPOSTA\*:?\s?', '', generated, flags=re.IGNORECASE | re.DOTALL).strip()
        generated = re.sub(r'(\*\*ESPACO DE EMOTES\*\*|\*\*ESPACO APRENDIDO\*\*):?.*?\s?', '', generated, flags=re.IGNORECASE | re.DOTALL).strip()
        
        return generated