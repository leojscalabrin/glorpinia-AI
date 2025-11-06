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
    Cliente para interagir com o modelo Gemini, agora configurado
    como um "Agente de Ferramentas" que pode decidir usar a busca.
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

        # Ferramenta de Python REAL
        try:
            self.search_tool = SearchTool()
        except Exception as e:
            logging.error(f"[GeminiClient] Falha ao inicializar SearchTool: {e}")
            self.search_tool = None

        # "Definição" da ferramenta para a IA
        self.web_search_tool = Tool(
            function_declarations=[
                FunctionDeclaration(
                    name="web_search",
                    description="Busca na internet em tempo real por fatos, notícias, clima, ou informações recentes que o modelo não possui.",
                    parameters=Schema(
                        type=Type.OBJECT,
                        properties={
                            "query": Schema(
                                type=Type.STRING, 
                                description="A pergunta ou termo de busca a ser pesquisado. Ex: 'previsão do tempo são paulo hoje' ou 'quem ganhou a copa de 2024'"
                            )
                        },
                        required=["query"]
                    ),
                )
            ]
        )

        # Inicializa o modelo
        self.model = genai.GenerativeModel(
            model_name="gemini-flash-latest",
            generation_config=self.generation_config,
            safety_settings=self.safety_settings,
            system_instruction=self.personality_profile,
            tools=[self.web_search_tool] if self.search_tool else None
        )


    def get_response(self, query, channel, author, memory_mgr: 'MemoryManager', recent_chat_history=None):
        """
        Gera uma resposta. (Loop de Agente).
        """
        clean_query = re.sub(r'@glorpinia\b', '', query, flags=re.IGNORECASE).strip()

        # Preparar Memória de Longo Prazo (RAG)
        memory_mgr.load_user_memory(channel, author)
        vectorstore = memory_mgr.vectorstore
        long_term_context = ""
        if vectorstore:
            try:
                # Usa a 'clean_query' para buscar no RAG
                retriever = vectorstore.as_retriever(search_kwargs={"k": 3})
                docs = retriever.invoke(clean_query) 
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
        
        # Montagem do Prompt Inicial
        # Passa a 'clean_query' para a IA
        prompt = f"""
        {short_term_context}
        {long_term_context}

        **Query do Usuário:** {clean_query} 
        """

        # Inicia uma sessão de chat
        chat_session = self.model.start_chat()
        
        try:
            # TURNO 1: Envia o prompt inicial
            response = chat_session.send_message(prompt)
            response_part = response.parts[0]
            
            if response_part.function_call:
                # O MODELO DECIDIU USAR A FERRAMENTA DE BUSCA
                logging.debug(f"[GeminiClient] IA decidiu usar a ferramenta de busca.")
                
                function_call = response_part.function_call
                
                if function_call.name == "web_search":
                    # Executa a ferramenta de busca
                    search_query_from_ai = function_call.args['query']
                    logging.info(f"[GeminiClient] IA está buscando por: {search_query_from_ai}")
                    
                    search_results = self.search_tool.perform_search(search_query_from_ai)
                    
                    if not search_results:
                        search_results = "A busca na internet não retornou nada."
                    
                    # TURNO 2: Envia os resultados da busca de volta para a IA
                    response = chat_session.send_message(
                        genai.Part(
                            function_response={
                                "name": "web_search",
                                "response": {"result": search_results}
                            }
                        )
                    )
                    generated = response.text.strip()
                
                else:
                    generated = "Ocorreu um glitch estranho nas minhas anteninhas... Sadge"

            else:
                # O MODELO RESPONDEU DIRETAMENTE
                generated = response.text.strip()

        except Exception as e:
            logging.error(f"[ERROR] Falha na comunicação com a API Gemini (Tool Use): {e}")
            generated = "O portal está instável. Eu não consigo me comunicar. Sadge"

        # Limpeza Final e Salvamento de Memória
        generated = self._clean_response(generated)
        fallback = "Meow. O portal está com lag. Tente novamente! 😸"
        is_system_message = (author.lower() == "system")

        if generated:
            if is_system_message:
                return generated
            else:
                # Salva a query original na memória
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
        
        generated = re.sub(r'\*\*(CONTEXTO APRENDIDO|HISTÓRICO RECENTE|CONTEXTO DA INTERNET)\*\*.*?\*RESPOSTA\*:?\s?', '', generated, flags=re.IGNORECASE | re.DOTALL).strip()
        generated = re.sub(r'(\*\*ESPACO DE EMOTES\*\*|\*\*ESPACO APRENDIDO\*\*):?.*?\s?', '', generated, flags=re.IGNORECASE | re.DOTALL).strip()
        
        return generated