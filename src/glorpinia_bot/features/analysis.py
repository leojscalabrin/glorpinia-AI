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
            # Pega as últimas 20 mensagens (ou 10 minutos)
            relevant_msgs = [m for m in recent_msgs if now - m['timestamp'] <= 600 and not m['content'].startswith("*")][-20:]
            chat_log = [f"- {m['author']}: {m['content']}" for m in relevant_msgs]
        
        if not chat_log:
            self.bot.send_message(channel, "**GL-0RP5:** Buffer de memória insuficiente. Conversem mais antes de pedir análise. glorp")
            return

        chat_context_str = "\n".join(chat_log)

        prompt = f"""
        [MODO: GL-0RP5 (ASSISTENTE TÁTICA)]
        [CONTEXTO: JOGO DE DETETIVE/ROLEPLAY]
        
        **TAREFA:**
        Responda à solicitação de @{author}: "{specific_query if specific_query else "Resuma a situação."}"
        baseada no chat abaixo.
        
        **REGRAS DE OURO (CONCISÃO):**
        1. **RESPOSTA CURTA:** Máximo de 3 frases. Sem listas, sem bullet points, sem "Processando dados".
        2. **IMPROVISE:** Se não houver "pistas" claras no texto, analise o *comportamento* dos usuários (quem falou mais, quem parece nervoso) e aponte um suspeito baseado nisso.
        3. **TOM:** Frio, calculista, mas direto ao ponto.
        
        **CHAT LOG:**
        {chat_context_str}
        
        **RESPOSTA GL-0RP5:**
        """

        try:
            response_text = self.bot.gemini_client.request_pure_analysis(prompt)

            if response_text:
                clean_text = response_text.replace("\n", " ").replace("  ", " ")
                
                if len(clean_text) > 450:
                    clean_text = clean_text[:447] + "..."

                self.bot.send_message(channel, clean_text)
        
        except Exception as e:
            logging.error(f"[Analysis] Falha: {e}")
            self.bot.send_message(channel, "**GL-0RP5:** Erro de compilação. glorp")