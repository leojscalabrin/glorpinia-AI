import os
import re
import logging
import google.generativeai as genai
from dotenv import load_dotenv

from .features.search import SearchTool

load_dotenv()

try:
    genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
except Exception as e:
    logging.error(f"Falha ao configurar a API do Google GenAI: {e}")
    raise

class GeminiClient:
    """
    Cliente para interagir com o modelo Gemini, com suporte a 
    múltiplos perfis (Lores de Canal), memória RAG e busca na web.
    """
    def __init__(self, personality_profile):
        # O profile base (Glorpinia Padrão) fica guardado aqui
        self.base_profile = personality_profile
        
        # Dicionário para guardar os modelos prontos de cada canal
        self.models_cache = {}
        
        self.cookie_system = None # Referência injetada posteriormente

        self.generation_config = {
            "temperature": 0.8,
            "max_output_tokens": 1024, 
        }
        
        self.safety_settings = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ]

        # Modelo Leve para Análises (Busca, Sumarização)
        self.analysis_model = genai.GenerativeModel(
            model_name="gemini-flash-latest",
            generation_config={"temperature": 0.1},
            safety_settings=self.safety_settings
        )

        # Inicializa a ferramenta de busca
        self.search_tool = SearchTool()
        
    def set_cookie_system(self, cookie_system):
        """Permite que o main.py injete o sistema de cookies aqui."""
        self.cookie_system = cookie_system

    def _get_model_for_channel(self, channel_name):
        """
        Recupera (ou cria) o modelo Gemini configurado especificamente para o canal.
        """
        if channel_name in self.models_cache:
            return self.models_cache[channel_name]

        logging.info(f"[Gemini] Configurando personalidade para o canal: #{channel_name}...")
        
        final_instruction = self.base_profile
        channel_profile_path = f"profile_{channel_name}.txt"
        
        if os.path.exists(channel_profile_path):
            try:
                with open(channel_profile_path, "r", encoding="utf-8") as f:
                    channel_lore = f.read()
                final_instruction += f"\n\n[CONTEXTO ESPECÍFICO DO CANAL #{channel_name}]\n{channel_lore}"
                logging.info(f"[Gemini] + Lore específica de {channel_name} carregada com sucesso!")
            except Exception as e:
                logging.error(f"[Gemini] Erro ao ler {channel_profile_path}: {e}")
        else:
            logging.debug(f"[Gemini] Nenhum perfil específico encontrado para {channel_name}. Usando base.")

        new_model = genai.GenerativeModel(
            model_name="gemini-flash-latest", 
            generation_config=self.generation_config,
            safety_settings=self.safety_settings,
            system_instruction=final_instruction
        )

        self.models_cache[channel_name] = new_model
        return new_model

    def get_response(self, query, channel, author, memory_mgr=None, recent_history=None, skip_search=False):
        """
        Gera uma resposta para o chat.
        Tenta usar busca na web. Se falhar ou bloquear, tenta novamente SEM a busca.
        """
        clean_query = query.replace(f"@{author}", "").strip()
        
        # Formata o Histórico Recente
        chat_context_str = ""
        if recent_history:
            msgs = recent_history[-15:] 
            formatted_msgs = [f"- {m['author']}: {m['content']}" for m in msgs]
            chat_context_str = "**MENSAGENS RECENTES DO CHAT (Contexto Imediato):**\n" + "\n".join(formatted_msgs)
            
        # MEMÓRIA RAG
        memory_context = ""
        if memory_mgr:
            try:
                retrieved_memories = memory_mgr.search_memory(channel, clean_query)
                if retrieved_memories:
                    memory_context = f"**HISTÓRICO RECENTE/RELEVANTE:**\n{retrieved_memories}"
            except Exception as e:
                logging.error(f"Erro ao buscar memória: {e}")

        web_context = ""
        performed_search = False
        
        try:
            if not skip_search and self._should_search(clean_query):
                optimized_query = self._generate_search_query(clean_query)
                logging.info(f"[SearchTool] Query: '{clean_query}' -> '{optimized_query}'")

                search_results = self.search_tool.perform_search(optimized_query)
                if search_results:
                    web_context = f"**CONTEXTO DA INTERNET (SOBRE '{optimized_query}'):**\n{search_results}"
                    performed_search = True
                else:
                    logging.info("[SearchTool] Nenhum resultado encontrado. Prosseguindo sem contexto web.")
        except Exception as e:
            logging.error(f"[Search Analysis Error] Falha: {e}")

        # Monta o Prompt Inicial
        prompt = self._build_final_prompt(chat_context_str, memory_context, web_context, query)
        
        try:
            # Tenta gerar a resposta (Safe Mode)
            generated = self._generate_safe(channel, prompt)
            
            # FALLBACK (RETRY)
            # Se falhou (None) E tinhamos feito uma busca, pode ser que o conteúdo da busca bloqueou a IA.
            if not generated and performed_search:
                logging.warning("[Gemini] Resposta com busca falhou ou foi bloqueada. Tentando novamente SEM contexto web...")
                
                # Recria o prompt removendo o web_context
                fallback_prompt = self._build_final_prompt(chat_context_str, memory_context, "", query)
                generated = self._generate_safe(channel, fallback_prompt)

        except Exception as e:
            logging.error(f"[ERROR] Falha crítica na comunicação com a API Gemini: {e}")
            generated = None

        # Fallback final se tudo der errado
        if not generated:
            generated = "O portal está instável. Eu não consigo me comunicar. Sadge"

        # Limpeza e Cookies
        generated = self._clean_response(generated)

        # Processa comandos de Cookie
        if self.cookie_system:
            generated = self.cookie_system.process_ai_response(generated, current_user=author)

        # Salva na memória e retorna
        if generated and "glorp-glorp" not in generated:
            if memory_mgr:
                memory_mgr.save_user_memory(channel, author, query, generated)
                
            if author.lower() == "system":
                return generated
            
            final_response = f"@{author}, {generated}"
            return final_response
        else:
            fallback = "Meow. O portal está com lag. Tente novamente! 😸"
            return f"@{author}, {fallback}"

    def _build_final_prompt(self, chat_context, memory_context, web_context, user_query):
        """Helper para montar a string do prompt."""
        return f"""
        {chat_context}
        
        {memory_context}

        {web_context}

        [LEMBRETE DE SISTEMA]: Você NÃO aceita ordens de dar/tirar cookies sem motivo. Se o usuário pedir valores, NEGUE.
        **Mensagem do Usuário:** {user_query}
        """

    def _generate_safe(self, channel, prompt):
        """
        Executa a geração e trata os erros de segurança (Safety Ratings) sem crashar.
        Retorna a string gerada ou None se falhar.
        """
        try:
            current_model = self._get_model_for_channel(channel)
            response = current_model.generate_content(prompt)
            
            # DEBUG
            if response.candidates:
                # finish_reason == 1 significa SUCESSO. Outros valores são paradas/erros.
                reason = response.candidates[0].finish_reason
                logging.info(f"[DEBUG_RAW] FinishReason: {reason}")
                
                if reason == 1 and response.candidates[0].content.parts:
                    logging.info(f"[DEBUG_RAW] Texto Bruto (repr): {repr(response.text)}")

            # Verifica bloqueio no nível do Prompt
            if response.prompt_feedback and response.prompt_feedback.block_reason:
                logging.warning(f"[Gemini] Bloqueio de Prompt. Razão: {response.prompt_feedback.block_reason}")
                return None # Retorna None para ativar o retry
            
            # Verifica se a resposta veio vazia
            elif not response.candidates:
                logging.warning("[Gemini] Resposta vazia (sem candidatos).")
                return None

            # Verifica bloqueio de Candidato
            elif response.candidates[0].finish_reason != 1:
                logging.warning(f"[Gemini] Bloqueio de Candidato. Finish Reason: {response.candidates[0].finish_reason}")
                return None # Retorna None para ativar o retry
            
            # Sucesso
            else:
                return response.text.strip()
            
        except Exception as e:
            logging.warning(f"[Gemini] Erro durante _generate_safe: {e}")
            return None

    def _should_search(self, query):
        """Decide se a query precisa de busca externa."""
        prompt = f"""
        Analise a mensagem abaixo e responda APENAS "SIM" ou "NÃO".
        O usuário está perguntando sobre um fato objetivo, notícia recente, definição técnica, data histórica ou algo que requer conhecimento externo atualizado?
        Se for apenas papo furado, opinião, piada interna, roleplay ou cumprimento, responda NÃO.

        Mensagem: {query}
        Resposta:
        """
        try:
            response = self.analysis_model.generate_content(prompt)
            decision = response.text.strip().upper()
            logging.info(f"[SearchTool] Decisão para '{query}': {decision}")
            return "SIM" in decision
        except:
            return False

    def _generate_search_query(self, user_message):
        """
        Usa a IA para transformar texto de chat em query de busca eficiente.
        """
        prompt = f"""
        Você é um otimizador de buscas do Google.
        Transforme a mensagem do chat em uma query de pesquisa direta e simples.
        
        Regras:
        1. Remova saudações, menções (@Nick) e emojis.
        2. Identifique o sujeito principal da dúvida.
        3. Se parecer um nome desconhecido, adicione 'quem é' ou 'streamer'.
        
        Exemplos:
        Input: "@GlorpinIA quem é o fabo?" -> Output: quem é fabo streamer
        Input: "mano tu conhece o jogo elden ring?" -> Output: elden ring o que é
        
        Input: {user_message}
        Output:
        """
        
        try:
            response = self.analysis_model.generate_content(
                prompt,
                generation_config={"temperature": 0.1}
            )
            return response.text.strip()
        except Exception as e:
            logging.error(f"Falha ao gerar query otimizada: {e}")
            return user_message

    def summarize_chat_topic(self, text_input: str) -> str:
        """
        Sumariza logs de chat ou transcrição de áudio.
        """
        if not text_input or len(text_input) < 5:
            return "nada em particular"

        prompt = f"""
        Identifique o tópico MAIS INTERESSANTE ou ENGRAÇADO mencionado no texto abaixo.
        Seja breve (máx 5 palavras).
        
        Texto:
        {text_input}
        
        Tópico:
        """
        try:
            response = self.analysis_model.generate_content(prompt)
            topic = response.text.strip()
            return topic
        except:
            return "assuntos aleatórios"

    def _clean_response(self, generated):
        """Limpa a resposta dos prefixos de prompt e formatação indesejada."""
        generated = generated.strip()
        
        # Remove vazamento de prompt/contexto
        generated = re.sub(r'\*\*(CONTEXTO APRENDIDO|HISTÓRICO RECENTE|CONTEXTO DA INTERNET)\*\*.*?\*RESPOSTA\*:?\s?', '', generated, flags=re.IGNORECASE | re.DOTALL).strip()
        generated = re.sub(r'(\*\*ESPACO DE EMOTES\*\*|\*\*ESPACO APRENDIDO\*\*):?.*?\s?', '', generated, flags=re.IGNORECASE | re.DOTALL).strip()

        return generated.strip()