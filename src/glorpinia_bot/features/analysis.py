import logging
import time

class AnalysisMode:
    def __init__(self, bot):
        self.bot = bot

    def trigger_analysis(self, channel, author, specific_query=""):
        logging.info(f"[Analysis] Triggered by {author} in {channel}")

        recent_msgs = list(self.bot.recent_messages.get(channel, []))
        
        now = time.time()
        chat_log = []
        if recent_msgs:
            relevant_msgs = [m for m in recent_msgs if now - m['timestamp'] <= 900 and not m['content'].startswith("*")][-25:]
            chat_log = [f"- {m['author']}: {m['content']}" for m in relevant_msgs]
        
        if not chat_log and not specific_query:
            self.bot.send_message(channel, "glorp **GL-0RP5:** *yawn* Logs vazios.")
            return

        chat_context_str = "\n".join(chat_log) if chat_log else "(Logs vazios)"

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
        - **FALA:** Coloque um leve toque de gírias de internet, games, animes e *glitches* na fala, como onomatopéias de máquinas e falhas elétricas. No máximo 2 referências por resposta. Ilustre as informações e conclusões com coisas que reforcem o roleplay de robótica e programação.
        - **SOCIAL:** Você é tímida e levemente agressiva porque quer voltar logo pro seu quarto jogar.
        
        **PROTOCOLO DE LINGUAGEM (CRÍTICO):**
        1. **MUNDO DIGITAL:** Interprete tudo como um Jogo. Pessoas são "Players" ou "NPCs".
        2. **METÁFORAS DE SISTEMA:** - Para descrever remoção ou fim de algo: Use "Deletar", "Banir", "Alt+F4", "Game Over". Use sinônimos destas palavras para não ficar repetitivo.
        3. **FORMATO:** Resposta curta (Max 280 chars). Seja direta e técnica. Evite fazer referências demais e seja pragmática e útil com suas respostas, de fácil entendimento.
        
        Inicie a resposta com: **GL-0RP5:** ou algum enfeite dessa forma que reforce o roleplay de programação
        """

        try:
            response_text = self.bot.gemini_client.request_pure_analysis(prompt)

            if response_text:
                clean_text = response_text.replace("\n", " ").replace("  ", " ")
                
                MAX_CHARS = 350
                
                if len(clean_text) > MAX_CHARS:
                    cut_text = clean_text[:MAX_CHARS]
                    
                    last_space = cut_text.rfind(" ")
                    
                    if last_space > 0:
                        final_msg = cut_text[:last_space] + "..."
                    else:
                        final_msg = cut_text + "..."
                else:
                    final_msg = clean_text

                self.bot.send_message(channel, final_msg)
        
        except Exception as e:
            logging.error(f"[Analysis] Falha: {e}")
            self.bot.send_message(channel, "glorp **GL-0RP5:** *CRASH* Erro no script.")