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
            "temperature": 0.7,
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
        Verifica se existe um arquivo 'profile_{canal}.txt' para adicionar lore extra.
        """
        # Se já carregamos esse canal antes, retorna o modelo do cache (memória RAM)
        if channel_name in self.models_cache:
            return self.models_cache[channel_name]

        # Se é a primeira vez, vamos construir o modelo
        logging.info(f"[Gemini] Configurando personalidade para o canal: #{channel_name}...")
        
        # Começa com a personalidade base da Glorpinia
        final_instruction = self.base_profile
        
        # Tenta carregar lore específica do canal
        channel_profile_path = f"profile_{channel_name}.txt"
        
        if os.path.exists(channel_profile_path):
            try:
                with open(channel_profile_path, "r", encoding="utf-8") as f:
                    channel_lore = f.read()
                
                # FUSÃO: Adiciona a lore do canal ao final do system prompt
                final_instruction += f"\n\n[CONTEXTO ESPECÍFICO DO CANAL #{channel_name}]\n{channel_lore}"
                logging.info(f"[Gemini] + Lore específica de {channel_name} carregada com sucesso!")
            except Exception as e:
                logging.error(f"[Gemini] Erro ao ler {channel_profile_path}: {e}")
        else:
            logging.debug(f"[Gemini] Nenhum perfil específico encontrado para {channel_name}. Usando base.")

        # Instancia o modelo para este canal
        new_model = genai.GenerativeModel(
            model_name="gemini-flash-latest", 
            generation_config=self.generation_config,
            safety_settings=self.safety_settings,
            system_instruction=final_instruction
        )

        # Salva no cache para não ter que ler arquivo de novo
        self.models_cache[channel_name] = new_model
        return new_model

    def get_response(self, query, channel, author, memory_mgr=None, recent_history=None):
        """
        Gera uma resposta para o chat, usando o modelo específico do canal.
        """
        # Limpa o input do usuário
        clean_query = query.replace(f"@{author}", "").strip()
        
        # Formata o Histórico Recente (Context Window)
        chat_context_str = ""
        if recent_history:
            # Pega as últimas 15 mensagens para não estourar tokens
            msgs = recent_history[-15:] 
            formatted_msgs = [f"- {m['author']}: {m['content']}" for m in msgs]
            chat_context_str = "**MENSAGENS RECENTES DO CHAT (Contexto Imediato):**\n" + "\n".join(formatted_msgs)
            
        # BUSCA NA WEB (Decisão Inteligente)
        web_context = ""
        try:
            if self._should_search(clean_query):
                # Usa a IA para limpar a query (ex: tira nicks, saudações)
                optimized_query = self._generate_search_query(clean_query)
                logging.info(f"[SearchTool] Query: '{clean_query}' -> '{optimized_query}'")

                # Faz a busca
                search_results = self.search_tool.perform_search(optimized_query)
                if search_results:
                    web_context = f"**CONTEXTO DA INTERNET (SOBRE '{optimized_query}'):**\n{search_results}"
        except Exception as e:
            logging.error(f"[Search Analysis Error] Falha: {e}")

        # MEMÓRIA RAG
        memory_context = ""
        if memory_mgr:
            try:
                retrieved_memories = memory_mgr.search_memory(channel, clean_query)
                if retrieved_memories:
                    memory_context = f"**HISTÓRICO RECENTE/RELEVANTE:**\n{retrieved_memories}"
            except Exception as e:
                logging.error(f"Erro ao buscar memória: {e}")

        # Monta o Prompt Final
        prompt = f"""
        {chat_context_str}
        
        {memory_context}

        {web_context}

        **Mensagem do Usuário:** {query}
        """

        try:
            # Pega o modelo correto para este canal (com ou sem lore extra)
            current_model = self._get_model_for_channel(channel)
            
            # Gera a resposta
            response = current_model.generate_content(prompt)
            generated = response.text.strip()
            
        except Exception as e:
            logging.error(f"[ERROR] Falha na comunicação com a API Gemini: {e}")
            generated = "O portal está instável. Eu não consigo me comunicar. Sadge"

        # Limpeza e Cookies
        generated = self._clean_response(generated)

        # Processa comandos de Cookie ocultos na resposta da IA
        if self.cookie_system:
            # Passamos o 'author' para saber se o cookie foi para ele ou para outro
            generated = self.cookie_system.process_ai_response(generated, current_user=author)

        # Salva na memória e retorna
        if generated and "glorp-glorp" not in generated:
            if memory_mgr:
                memory_mgr.save_user_memory(channel, author, query, generated)
            
            final_response = f"@{author}, {generated}"
            return final_response
        else:
            return f"@{author}, Meow. O portal está com lag. Tente novamente! 😸"

    def _should_search(self, query):
        """Decide se a query precisa de busca externa."""
        prompt = f"""
        Analise a mensagem abaixo e responda APENAS "SIM" ou "NÃO".
        O usuário está perguntando sobre um fato objetivo, notícia recente, definição técnica, data histórica ou algo que requer conhecimento externo atualizado?
        Se for apenas papo furado, opinião, roleplay ou cumprimento, responda NÃO.

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
        """Limpa a resposta dos prefixos de prompt e metadados."""
        generated = generated.strip()
        # Remove blocos de contexto que a IA as vezes repete
        generated = re.sub(r'\*\*(CONTEXTO APRENDIDO|HISTÓRICO RECENTE|CONTEXTO DA INTERNET)\*\*.*?\*RESPOSTA\*:?\s?', '', generated, flags=re.IGNORECASE | re.DOTALL).strip()
        # Remove timestamps ou prefixos de log
        generated = re.sub(r'^\[.*?\]\s*', '', generated)
        return generated