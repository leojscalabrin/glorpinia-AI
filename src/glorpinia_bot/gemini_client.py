import os
import re
import logging
import google.generativeai as genai

from langchain_core.messages import HumanMessage, AIMessage
from .memory_manager import MemoryManager
from dotenv import load_dotenv

from .features.search import SearchTool

load_dotenv()

from google.generativeai.types import Tool, FunctionDeclaration
from google.ai.generativelanguage import Schema, Type

try:
    genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
except Exception as e:
    logging.error(f"Falha ao configurar a API do Google GenAI: {e}")
    raise

class GeminiClient:
    """
    Cliente para interagir com o modelo Gemini, com
    memória de curto prazo, longo prazo (RAG) e busca na web (via Análise de IA).
    """
    def __init__(self, personality_profile):
        self.personality_profile = personality_profile
        
        self.cookie_system = None # Referência ao sistema de cookies

        self.generation_config = {
            "temperature": 0.7,
            "max_output_tokens": 2048, 
        }
        
        self.safety_settings = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ]

        # Modelo principal (para respostas)
        self.model = genai.GenerativeModel(
            model_name="gemini-pro-latest",
            generation_config=self.generation_config,
            safety_settings=self.safety_settings,
            system_instruction=self.personality_profile 
        )
        
        # Modelo leve (apenas para decidir se busca ou não)
        self.analysis_model = genai.GenerativeModel(
            model_name="gemini-pro-latest",
            generation_config={"temperature": 0.0},
            safety_settings=self.safety_settings 
        )
        
        # Inicializa a ferramenta de busca
        try:
            self.search_tool = SearchTool()
        except Exception as e:
            logging.error(f"[GeminiClient] Falha ao inicializar SearchTool: {e}")
            self.search_tool = None
    
    def set_cookie_system(self, cookie_system):
        """Recebe a instância do CookieSystem para executar ordens da IA."""
        self.cookie_system = cookie_system
        print("[GeminiClient] CookieSystem conectado com sucesso.")

    def _build_search_analysis_prompt(self, query: str) -> str:
        """
        Cria um prompt específico para a IA decidir se a busca é necessária.
        """
        return f"""
        Você é um assistente de análise de busca. Sua única tarefa é decidir se a pergunta do usuário precisa de uma busca na internet para ser respondida.
        A IA (Glorpinia) NÃO tem conhecimento de eventos após 2023, pessoas específicas pouco conhecidas, ou dados em tempo real (como clima ou resultados de jogos).

        Responda APENAS 'SIM' ou 'NÃO'.

        Responda 'SIM' se a pergunta for sobre:
        - Eventos recentes (notícias de hoje, "o que aconteceu ontem")
        - Pessoas, lugares ou fatos históricos/reais (ex: "quem é o presidente da frança?", "o que é o 'Alabama Hot Pocket'?")
        - Informações em tempo real (ex: "vai chover hoje?", "qual o resultado do jogo X?")

        Responda 'NÃO' se a pergunta for:
        - Uma conversa fiada (ex: "oi, tudo bem?", "qual sua cor favorita?")
        - Uma pergunta sobre a PRÓPRIA IA (ex: "você é uma IA?", "qual seu nome?")
        - Um comando (ex: "!glorp cookie")

        Pergunta do Usuário: "{query}"
        Decisão (SIM/NÃO):
        """

    def _should_search(self, query: str) -> bool:
        """
        Decide se uma query deve ou não disparar uma busca na web.
        """
        if not self.search_tool:
            return False 

        if query.lower().startswith('*'):
            return False

        # Monta o prompt de análise
        analysis_prompt = self._build_search_analysis_prompt(query)
        
        try:
            response = self.analysis_model.generate_content(analysis_prompt)
            decision = response.text.strip().upper()
            logging.info(f"[SearchTool] Análise de busca para '{query}'. Decisão da IA: {decision}")
            return decision == "SIM"
        except Exception as e:
            logging.error(f"[SearchTool] Erro na ANÁLISE de busca: {e}")
            return False 

    def _process_cookie_commands(self, text: str, interaction_author: str) -> str:
        """
        Procura por tags, executa a ação E substitui a tag pelo feedback visual formatado.
        """
        if not self.cookie_system or "[[COOKIE:" not in text:
            return text

        pattern = r'\[\[COOKIE:(GIVE|TAKE):([a-zA-Z0-9_]+):(\d+)\]\]'

        def replace_match(match):
            action = match.group(1)
            target_user = match.group(2).lower()
            try:
                amount = int(match.group(3))
                
                # Executa a transação real
                if action == "GIVE":
                    self.cookie_system.add_cookies(target_user, amount)
                    logging.info(f"[IA-ECONOMY] IA deu {amount} cookies para {target_user}.")
                    
                    # Formatação condicional
                    if target_user == interaction_author.lower():
                        return f"(+{amount} 🍪)" # Se for para quem falou
                    else:
                        return f"(+{amount} 🍪 para {target_user})" # Se for para outro
                
                elif action == "TAKE":
                    self.cookie_system.remove_cookies(target_user, amount)
                    logging.info(f"[IA-ECONOMY] IA removeu {amount} cookies de {target_user}.")
                    
                    # Formatação condicional
                    if target_user == interaction_author.lower():
                        return f"(-{amount} 🍪)" # Se for de quem falou
                    else:
                        return f"(-{amount} 🍪 de {target_user})" # Se for de outro
                    
            except Exception as e:
                logging.error(f"[IA-ECONOMY] Erro ao processar tag: {e}")
                return "" # Remove a tag se der erro
            
            return "" # Fallback

        new_text = re.sub(pattern, replace_match, text)
        
        return re.sub(r'\s+', ' ', new_text).strip()


    def get_response(self, query, channel, author, memory_mgr: 'MemoryManager', recent_chat_history=None):
        """
        Gera uma resposta (Passagem 2), com memórias e busca na web.
        """
        
        clean_query = re.sub(r'@glorpinia\b[,\s]*', '', query, flags=re.IGNORECASE).strip()

        # Preparar Memória de Longo Prazo (RAG)
        memory_mgr.load_user_memory(channel, author)
        vectorstore = memory_mgr.vectorstore
        long_term_context = ""
        if vectorstore:
            try:
                retriever = vectorstore.as_retriever(search_kwargs={"k": 1})
                docs = retriever.invoke(clean_query) 
                if docs:
                    long_term_context = "\n".join([doc.page_content for doc in docs])
                    long_term_context = f"**CONTEXTO APRENDIDO (MEMÓRIA GLORPINIA):**\n{long_term_context}"
            except Exception as e:
                logging.error(f"[RAG ERROR] Falha ao buscar contexto: {e}")
        
        # Preparar Memória de Curto Prazo (Histórico Recente)
        short_term_context = ""
        if recent_chat_history:
            recent_messages = list(recent_chat_history)[-3:] 
            if recent_messages:
                formatted_history = "\n".join([
                    f"{msg['author']}: {msg['content']}" for msg in recent_messages
                ])
                short_term_context = f"**HISTÓRICO RECENTE (MEMÓRIA IMEDIATA):**\n{formatted_history}"
        
        # Preparar Contexto da Web
        web_context = ""
        try:
            if self._should_search(clean_query):
                search_results = self.search_tool.perform_search(clean_query)
                if search_results:
                    web_context = f"**CONTEXTO DA INTERNET (BUSCA EM TEMPO REAL):**\n{search_results}"
        except Exception as e:
             logging.error(f"[Search Analysis Error] Falha ao decidir/buscar: {e}")

        # Montagem do Prompt
        prompt = f"""
        {short_term_context}

        {long_term_context}

        {web_context}

        **Query do Usuário:** {clean_query} 
        """

        # Chamada à API do Gemini
        try:
            response = self.model.generate_content(prompt)

            if response.prompt_feedback and response.prompt_feedback.block_reason:
                reason = response.prompt_feedback.block_reason.name
                logging.warning(f"[SAFETY] Prompt bloqueado. Razão: {reason}")
                generated = f"Minhas anteninhas detectaram interferência perigosa ({reason}). Tente reformular. Sadge"
            
            elif not response.parts:
                finish_reason = "DESCONHECIDO"
                if response.candidates and response.candidates[0].finish_reason:
                     finish_reason = response.candidates[0].finish_reason.name
                
                logging.warning(f"[SAFETY/EMPTY] Resposta vazia. Finish Reason: {finish_reason}")
                generated = f"O sinal caiu no meio do caminho... (Razão: {finish_reason}). Sadge"
            else:
                generated = response.text.strip()

        except Exception as e:
            logging.error(f"Falha na comunicação com a API Gemini: {e}")
            generated = "O portal está instável. Eu não consigo me comunicar. Sadge"

        generated = self._process_cookie_commands(generated, author)

        # Limpeza Final e Salvamento de Memória
        generated = self._clean_response(generated)
        fallback = "Meow. O portal está com lag. Tente novamente! 😸"
        is_system_message = (author.lower() == "system")

        if generated:
            if is_system_message:
                return generated, None
            else:
                if "Sadge" not in generated: 
                    memory_mgr.save_user_memory(channel, author, query, generated)
                
                final_response = f"@{author}, {generated}"
                return final_response, None
        else:
            if is_system_message:
                return fallback
            else:
                final_fallback = f"@{author}, {fallback}"
                return final_fallback

    def _clean_response(self, generated):
        """Limpa a resposta dos prefixos de prompt."""
        generated = generated.strip()
        
        generated = re.sub(r'\*\*(CONTEXTO APRENDIDO|HISTÓRICO RECENTE|CONTEXTO DA INTERNET)\*\*.*?\*RESPOSTA\*:?\s?', '', generated, flags=re.IGNORECASE | re.DOTALL).strip()
        generated = re.sub(r'(\*\*ESPACO DE EMOTES\*\*|\*\*ESPACO APRENDIDO\*\*):?.*?\s?', '', generated, flags=re.IGNORECASE | re.DOTALL).strip()
        
        return generated

    def summarize_chat_topic(self, text_input: str) -> str:
        """
        Usa o 'analysis_model' para extrair o tópico principal de um texto (audio ou chat).
        """
        if not text_input or len(text_input) < 5:
            return "nada em particular"

        prompt = f"""
        Você é um analisador de conteúdo. Abaixo está a transcrição de um áudio ou chat.
        Sua tarefa é identificar o tópico MAIS INTERESSANTE, ENGRAÇADO ou CURIOSO mencionado.
        
        Se houver vários assuntos misturados, ESCOLHA APENAS UM (o que renderia o melhor comentário sarcástico).
        NÃO responda "assuntos aleatórios" ou "nada". Invente um título para o assunto se necessário.

        Texto:
        ---
        {text_input}
        ---
        Tópico Principal (apenas o assunto):
        """

        try:
            response = self.analysis_model.generate_content(prompt)
            if response.parts:
                topic = response.text.strip().replace("Tópico Principal:", "").strip()
                logging.info(f"[Summarizer] Tópico extraído: {topic}")
                return topic
            return "a vida no universo"
        except Exception as e:
            logging.error(f"[Summarizer] Falha: {e}")
            return "o silêncio do espaço"