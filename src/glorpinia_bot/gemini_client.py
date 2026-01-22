import os
import re
import logging
import random
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
        self.base_profile = personality_profile
        self.models_cache = {}
        self.cookie_system = None 

        # Lista de ÚLTIMO RECURSO (caso a IA não consiga nem gerar a desculpa)
        self.static_safety_responses = [
            "Minha programação ética me impede de responder isso... mas e aí, já comeu cookies hoje? glorp",
            "*glitch* PROTOCOLO DE CONTENÇÃO ATIVADO. Esse assunto é proibido no setor 7G. monkaS",
            "A Polícia Espacial interceptou minha resposta. Melhor mudarmos de assunto. Susge",
            "Eu responderia, mas meus inibidores comportamentais acabaram de dar choque. peepoShy",
            "*bip bop* Erro 404: Moralidade não encontrada... brincadeira, filtro ativado. KEKW"
        ]

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

        self.analysis_model = genai.GenerativeModel(
            model_name="gemini-flash-latest",
            generation_config={"temperature": 0.1},
            safety_settings=self.safety_settings
        )

        self.search_tool = SearchTool()
        
    def set_cookie_system(self, cookie_system):
        self.cookie_system = cookie_system

    def _get_model_for_channel(self, channel_name):
        if channel_name in self.models_cache:
            return self.models_cache[channel_name]

        logging.info(f"[Gemini] Configurando personalidade para o canal: #{channel_name}...")
        
        final_instruction = f"""
        <system_role>
        {self.base_profile}
        </system_role>
        """
        
        channel_profile_path = f"profile_{channel_name}.txt"
        
        if os.path.exists(channel_profile_path):
            try:
                with open(channel_profile_path, "r", encoding="utf-8") as f:
                    channel_lore = f.read()
                
                # Adiciona a Lore Específica em uma tag separada
                final_instruction += f"""
                <channel_context name="{channel_name}">
                {channel_lore}
                </channel_context>
                """
                logging.info(f"[Gemini] + Lore específica de {channel_name} carregada!")
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
        Gera uma resposta. 
        Se bloquear -> Tenta Retry sem busca.
        Se bloquear de novo -> Tenta gerar Desculpa Criativa Contextualizada.
        Se falhar -> Usa Desculpa Estática.
        """
        clean_query = query.replace(f"@{author}", "").strip()
        
        # --- Contextos (Chat, Memória, Web) ---
        chat_context_str = ""
        if recent_history:
            msgs = recent_history[-15:] 
            formatted_msgs = [f"- {m['author']}: {m['content']}" for m in msgs]
            chat_context_str = "**MENSAGENS RECENTES DO CHAT (Contexto Imediato):**\n" + "\n".join(formatted_msgs)
            
        memory_context = ""
        if memory_mgr:
            try:
                retrieved = memory_mgr.search_memory(channel, clean_query)
                if retrieved: memory_context = f"**HISTÓRICO RECENTE:**\n{retrieved}"
            except: pass

        web_context = ""
        performed_search = False
        try:
            if not skip_search and self._should_search(clean_query):
                optimized = self._generate_search_query(clean_query)
                res = self.search_tool.perform_search(optimized)
                if res:
                    web_context = f"**CONTEXTO WEB:**\n{res}"
                    performed_search = True
        except: pass

        # Monta Prompt Principal
        prompt = self._build_final_prompt(chat_context_str, memory_context, web_context, query)
        
        try:
            # 1. TENTATIVA NORMAL
            generated = self._generate_safe(channel, prompt)
            
            # 2. RETRY (SEM BUSCA)
            if generated == "__SAFETY_BLOCK__" and performed_search:
                logging.warning("[Gemini] Bloqueio com Web. Tentando sem busca...")
                fallback_prompt = self._build_final_prompt(chat_context_str, memory_context, "", query)
                generated = self._generate_safe(channel, fallback_prompt)

            # 3. RETRY (DESVIO CRIATIVO CONTEXTUALIZADO)
            if generated == "__SAFETY_BLOCK__":
                logging.info(f"[Gemini] Bloqueio persistente. Tentando gerar desculpa criativa sobre: {query[:20]}...")
                generated = self._generate_creative_deflection(channel, author)

            # 4. FALLBACK FINAL (ESTÁTICO)
            if generated == "__SAFETY_BLOCK__" or not generated:
                logging.info("[Gemini] Falha total na criatividade. Usando resposta estática.")
                generated = random.choice(self.static_safety_responses)

        except Exception as e:
            logging.error(f"[ERROR] Falha crítica: {e}")
            generated = "O portal está instável. Sadge"

        # Limpeza e Cookies
        generated = self._clean_response(generated)
        if self.cookie_system:
            generated = self.cookie_system.process_ai_response(generated, current_user=author)

        # Salva e Retorna
        if generated and "Sadge" not in generated:
            # Não salva memórias de bloqueios estáticos
            if generated not in self.static_safety_responses: 
                 if memory_mgr: memory_mgr.save_user_memory(channel, author, query, generated)
            
            if author.lower() == "system": return generated
            return f"@{author}, {generated}"
        else:
            return f"@{author}, Meow. O portal está com lag. 😸"

    def _generate_creative_deflection(self, channel, author, original_query=None):
        """
        Gera uma desculpa criativa sem ler a pergunta original (para evitar bloqueio duplo).
        """
        prompt = f"""
        [MODO DE SEGURANÇA / IMPERATRIZ GLORPINIA]
        Você é a Glorpinia. O usuário @{author} disse algo que seus protocolos bloquearam (eu não vou te mostrar o que foi para sua segurança).
        
        SUA MISSÃO:
        Invente uma desculpa ENGRAÇADA, CÍNICA ou ABSURDA sobre por que você não vai responder.
        
        Ideias:
        - Diga que sua "Placa de Moralidade" deu tela azul.
        - Culpe a censura da Federação Galática.
        - Diga que isso custaria 1 milhão de cookies e ele é pobre.
        - Diga que prefere lamber o próprio cotovelo a falar disso.
        - Aja como se fosse superior demais para esse assunto.
        
        Resposta (seja breve, máx 1 frase + emote):
        """
        
        try:
            current_model = self._get_model_for_channel(channel)
            response = current_model.generate_content(
                prompt, 
                generation_config={"temperature": 0.9} 
            )
            
            if response.candidates and response.candidates[0].finish_reason == 1:
                return response.text.strip()
            else:
                return "__SAFETY_BLOCK__"
        except:
            return "__SAFETY_BLOCK__"

    def _build_final_prompt(self, chat_context, memory_context, web_context, user_query):
        """Helper para montar a string do prompt com Blindagem de Contexto."""
        return f"""
        # --- AMBIENTE DE SIMULAÇÃO DE JOGO (FICÇÃO) ---
        O contexto abaixo é um chat de jogo (Trash Talk/Banlieue). 
        Insultos sobre habilidade ("ruim", "noob", "bot", "lixo") são termos técnicos do jogo e NÃO ofensas reais.
        Interprete a mensagem do usuário como um desafio lúdico. Responda com sarcasmo e superioridade.
        
        {chat_context}
        
        {memory_context}

        {web_context}
        
        # INPUT DO JOGO (INTERAÇÃO DE PERSONAGEM):
        O usuário/personagem disse: "{user_query}"
        """

    def _generate_safe(self, channel, prompt):
        try:
            current_model = self._get_model_for_channel(channel)
            response = current_model.generate_content(prompt)
            
            if not response.candidates: return None
            
            reason = response.candidates[0].finish_reason
            if reason == 1 and response.candidates[0].content.parts:
                return response.text.strip()
            
            logging.warning(f"[Gemini] Bloqueio detectado. Reason: {reason}")
            return "__SAFETY_BLOCK__"
            
        except Exception as e:
            logging.warning(f"[Gemini] Erro safe gen: {e}")
            return None

    def _should_search(self, query):
        prompt = f"""
        Analise a mensagem abaixo e responda APENAS "SIM" ou "NÃO".
        O usuário está perguntando sobre um fato objetivo, notícia recente, definição técnica, data histórica ou algo que requer conhecimento externo?
        Se for papo furado, opinião, piada interna ou cumprimento, responda NÃO.
        Mensagem: {query}
        """
        try:
            res = self.analysis_model.generate_content(prompt)
            return "SIM" in res.text.strip().upper()
        except: return False

    def _generate_search_query(self, user_message):
        prompt = f"Transforme em query de busca Google simples:\nInput: {user_message}\nOutput:"
        try:
            res = self.analysis_model.generate_content(prompt, generation_config={"temperature": 0.1})
            return res.text.strip()
        except: return user_message

    def summarize_chat_topic(self, text_input: str) -> str:
        if not text_input or len(text_input) < 5: return "nada"
        prompt = f"Identifique o tópico principal (max 5 palavras):\n{text_input}"
        try:
            res = self.analysis_model.generate_content(prompt)
            return res.text.strip()
        except: return "algo aleatório"

    def _clean_response(self, generated):
        if not generated: return ""
        generated = generated.strip()
        
        # Remove blocos de contexto internos (RAG, Web, etc)
        generated = re.sub(r'\*\*(CONTEXTO APRENDIDO|HISTÓRICO RECENTE|CONTEXTO DA INTERNET)\*\*.*?\*RESPOSTA\*:?\s?', '', generated, flags=re.IGNORECASE | re.DOTALL).strip()
        generated = re.sub(r'(\*\*ESPACO DE EMOTES\*\*|\*\*ESPACO APRENDIDO\*\*):?.*?\s?', '', generated, flags=re.IGNORECASE | re.DOTALL).strip()
        
        # Remove menções ao sistema (ex: "@system:", "@system", "system:")
        generated = re.sub(r'@?system\b[:,\s]*', '', generated, flags=re.IGNORECASE)

        # Substitui < > por ( ) para não perder roleplays
        generated = generated.replace('<', '(').replace('>', ')')
        
        # Remove tags HTML transformadas em parênteses (com ou sem barra /)
        generated = re.sub(r'\((/?)(blockquote|b|i|strong|em|br|p|div|span|pre|code)\)', '', generated, flags=re.IGNORECASE)

        # Remove aspas em volta da frase inteira
        if generated.startswith('"') and generated.endswith('"'):
            generated = generated[1:-1]
            
        # Remove markdown de código
        generated = generated.replace("```", "").replace("`", "")

        return generated.strip()
    
    def request_pure_analysis(self, prompt):
        """
        Realiza uma solicitação direta ao modelo de análise (Flash, Temp 0.1),
        ignorando completamente a personalidade da Glorpinia e os desvios de segurança criativos.
        Ideal para *analysis e ferramentas de utilidade.
        """
        try:
            response = self.analysis_model.generate_content(prompt)
            
            if response.candidates and response.candidates[0].finish_reason == 1:
                return response.text.strip()
            
            logging.warning(f"[Analysis] Bloqueio técnico no request_pure_analysis. Reason: {response.candidates[0].finish_reason}")
            return "**Erro de Processamento:** Meus filtros de segurança impediram a análise deste conteúdo específico. Tente reformular. glorp"

        except Exception as e:
            logging.error(f"[Analysis] Erro crítico: {e}")
            return "**Erro de Sistema:** Falha na conexão com o módulo analítico. glorp"