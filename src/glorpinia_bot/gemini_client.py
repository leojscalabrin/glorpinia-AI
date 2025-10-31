import os
import re
import logging
import google.generativeai as genai
from langchain.schema import HumanMessage, AIMessage
from .memory_manager import MemoryManager
from dotenv import load_dotenv

load_dotenv()

try:
    genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
except Exception as e:
    logging.error(f"Falha ao configurar a API do Google GenAI: {e}")
    raise

class GeminiClient:
    """
    Cliente para interagir com o modelo Gemini 1.5 Flash via API GenAI.
    """
    def __init__(self, personality_profile):
        self.personality_profile = personality_profile
        
        # Configurações de geração (segurança e parâmetros)
        self.generation_config = {
            "temperature": 0.7,
            "max_output_tokens": 1024,
        }
        
        # Configurações de segurança (para permitir o roleplay)
        self.safety_settings = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ]

        # Inicializa o modelo
        self.model = genai.GenerativeModel(
            model_name="gemini-flash-latest",
            generation_config=self.generation_config,
            safety_settings=self.safety_settings,
            system_instruction=self.personality_profile 
        )

    def get_response(self, query, channel, author, memory_mgr: 'MemoryManager'):
        """
        Gera uma resposta usando a API Gemini, injetando RAG como contexto.
        """
        memory_mgr.load_user_memory(channel, author)
        vectorstore = memory_mgr.vectorstore
        
        # Recuperação de Contexto (RAG/Memória de Longo Prazo)
        long_term_context = ""
        if vectorstore:
            try:
                retriever = vectorstore.as_retriever(search_kwargs={"k": 3})
                docs = retriever.invoke(query)
                
                if docs:
                    long_term_context = "\n".join([doc.page_content for doc in docs])
                    # Formata o RAG para o prompt do Gemini
                    long_term_context = f"**CONTEXTO APRENDIDO (MEMÓRIA GLORPINIA):** {long_term_context}"
            except Exception as e:
                logging.error(f"[RAG ERROR] Falha ao buscar contexto: {e}")

        # Montagem do Prompt Final (RAG + Query)
        # O System Prompt já foi definido no __init__ do modelo.
        prompt = f"""
        {long_term_context}

        **Query do Usuário:** {query}
        """

        # hamada à API do Gemini
        try:
            response = self.model.generate_content(prompt)

            # Verificação de segurança ANTES de tentar ler o .text
            if not response.parts:
                # A resposta foi bloqueada ou veio vazia
                finish_reason = "DESCONHECIDO"
                if response.candidates and response.candidates[0].finish_reason:
                    finish_reason = response.candidates[0].finish_reason.name # Pega o nome (ex: SAFETY)

                logging.error(f"[ERROR] A API Gemini não retornou 'parts'. Finish Reason: {finish_reason}")
                
                if finish_reason == "SAFETY":
                    generated = "glorp [REDACTED]"
                else:
                    generated = f"Minhas anteninhas não captaram nenhum sinal (Razão: {finish_reason}). Sadge"
            else:
                # Se tudo estiver OK, agora sim podemos ler o texto
                generated = response.text.strip()

        except Exception as e:
            logging.error(f"[ERROR] Falha na comunicação com a API Gemini: {e}")
            generated = "O portal está instável. Eu não consigo me comunicar. Sadge"

        # impeza Final e Salvamento de Memória
        generated = self._clean_response(generated)

        if generated and "glorp-glorp" not in generated:
            # Salva a interação query/response na memória de longo prazo (RAG)
            memory_mgr.save_user_memory(channel, author, query, generated)
            
            final_response = f"@{author}, {generated}"
            return final_response
        else:
            fallback = "Meow. O portal está com lag. Tente novamente! 😸"
            final_fallback = f"@{author}, {fallback}"
            return final_fallback

    def _clean_response(self, generated):
        
        generated = generated.strip()
        
        # Limpeza de lixo de RAG (se a memória antiga ainda estiver suja)
        generated = re.sub(r'\*\*CONTEXTO APRENDIDO\*\*.*?\*RESPOSTA\*:?\s?', '', generated, flags=re.IGNORECASE).strip()
        generated = re.sub(r'(\*\*ESPACO DE EMOTES\*\*|\*\*ESPACO APRENDIDO\*\*):?.*?\s?', '', generated, flags=re.IGNORECASE).strip()
        
        return generated