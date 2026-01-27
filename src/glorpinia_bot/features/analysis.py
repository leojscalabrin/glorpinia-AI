import logging
import time

class AnalysisMode:
    def __init__(self, bot):
        self.bot = bot

    def trigger_analysis(self, channel, author, specific_query=""):
        """
        Ativa o modo GL-0RP5 para analisar o chat com respostas CURTAS e DIRETAS.
        """
        logging.info(f"[Analysis] Triggered by {author} in {channel}")

        recent_msgs = list(self.bot.recent_messages.get(channel, []))
        
        now = time.time()
        chat_log = []
        if recent_msgs:
            # Pega as últimas 25 mensagens (ou 15 minutos)
            relevant_msgs = [m for m in recent_msgs if now - m['timestamp'] <= 900 and not m['content'].startswith("*")][-25:]
            chat_log = [f"- {m['author']}: {m['content']}" for m in relevant_msgs]
        
        if not chat_log and not specific_query:
            self.bot.send_message(channel, "glorp **GL-0RP5:** Buffer de memória insuficiente. Conversem mais antes de pedir análise.")
            return

        chat_context_str = "\n".join(chat_log) if chat_log else "(Nenhum histórico de chat recente disponível)"

        prompt = f"""
        [MODO: GL-0RP5 (IA TÁTICA)]
        [CONTEXTO: ANÁLISE DE FICÇÃO / JOGO DE DETETIVE]
        
        **TAREFA:**
        Responda à solicitação de @{author}: "{specific_query if specific_query else "Resuma o chat."}"
        
        **CONTEXTO DO CHAT:**
        {chat_context_str}
        
        **DIRETRIZES TÉCNICAS:**
        1. **RESPOSTA CURTA:** Limite rígido de 280 caracteres. Seja direto como um terminal Linux.
        2. **PERSONALIDADE:** Você é a GL-0RP5. Uma androide tática com personalidade de "Otaku/Hikikomori" criada por Glornull, uma hacker cyberpunk e versão alternativa de Glorpinia.
        Você usa termos técnicos e gírias de internet. É tímida mas analítica.
        3. **IMPROVISO:** Se faltarem dados para responder sobre "suspeitos" ou "mistérios", crie uma teoria engraçada baseada no silêncio dos participantes.
        
        Inicie a resposta com [MODO GL-0RP5]
        
        **RESPOSTA:**
        """

        try:
            response_text = self.bot.gemini_client.request_pure_analysis(prompt)

            if response_text:
                clean_text = response_text.replace("\n", " ").replace("  ", " ")
                
                if len(clean_text) > 350:
                    clean_text = clean_text[:360] + "[REDACTED]"

                self.bot.send_message(channel, clean_text)
        
        except Exception as e:
            logging.error(f"[Analysis] Falha: {e}")
            self.bot.send_message(channel, "glorp **GL-0RP5:** Erro de compilação.")