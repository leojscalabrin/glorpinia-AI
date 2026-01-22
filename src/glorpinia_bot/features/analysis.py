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

        # Coleta e Filtra o Contexto
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
        [MODO: GL-0RP5 (ASSISTENTE TÁTICA)]
        [CONTEXTO: JOGO DE DETETIVE/ROLEPLAY/ANÁLISE]
        
        **TAREFA:**
        Atue como uma IA Tática. Responda à solicitação de @{author}: "{specific_query if specific_query else "Resuma a situação do chat."}"
        
        **CONTEXTO DISPONÍVEL:**
        {chat_context_str}
        
        **REGRAS DE OURO:**
        1. **RESPOSTA CURTA:** Máximo de 3 frases. Seja direto.
        2. **IMPROVISE COM LÓGICA:** Se o usuário perguntou sobre "suspeitos" ou "pistas" e o chat estiver vazio ou confuso, NÃO diga "dados insuficientes". Diga que "a ausência de dados sugere um crime silencioso" ou invente uma teoria baseada na falta de álibis. Jogue o jogo!
        3. **TOM:** Frio, calculista e tecnológico.
        
        **RESPOSTA GL-0RP5:**
        """

        try:
            response_text = self.bot.gemini_client.request_pure_analysis(prompt)

            if response_text:
                clean_text = response_text.replace("\n", " ").replace("  ", " ")
                
                if len(clean_text) > 480:
                    clean_text = clean_text[:477] + "..."

                self.bot.send_message(channel, clean_text)
        
        except Exception as e:
            logging.error(f"[Analysis] Falha: {e}")
            self.bot.send_message(channel, "glorp **GL-0RP5:** Erro de compilação.")