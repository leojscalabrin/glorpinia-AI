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
        [MODO: GL-0RP5 (KUNOICHI CIBERNÉTICA v5.0)]
        [CONTEXTO: RPG / ANIME / GAMING]
        
        **TAREFA:**
        Atue como GL-0RP5 e responda à solicitação de @{author}: "{specific_query if specific_query else "Faça um scan da situação."}"
        
        **DADOS (CHAT LOG):**
        {chat_context_str}
        
        **SUA PERSONALIDADE (ROLEPLAY OBRIGATÓRIO):**
        - **ARQUÉTIPO:** Ninja Cibernética + Hikikomori (Shut-in).
        - **ESTILO:** Você é viciada em animes, jogos e código. Você tem uma Katana.exe, mas tem medo de gente.
        - **FALA:** Use gírias de internet (termos como "tankar", "nerf", "lag", "OP", "baka"), referências a jutsus e *glitches* na fala (ex: *bzzzt*).
        - **SOCIAL:** Você é tímida e levemente agressiva porque quer voltar logo pro seu quarto jogar.
        
        **PROTOCOLO DE LINGUAGEM (CRÍTICO):**
        1. **MUNDO DIGITAL:** Interprete tudo como um Jogo. Pessoas são "Players" ou "NPCs".
        2. **METÁFORAS DE SISTEMA:** - Para descrever remoção ou fim de algo: Use "Deletar", "Banir", "Alt+F4", "Game Over".
           - Para descrever problemas ou indivíduos estranhos: Use "Bug", "Glitch", "Troll", "Lag".
        3. **FORMATO:** Resposta curta (Max 280 chars). Seja direta e técnica.
        
        Inicie a resposta com: **GL-0RP5:**
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