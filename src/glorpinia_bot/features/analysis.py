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
        Você é uma assistente de IA
        """

        try:
            response_text = self.bot.gemini_client.request_pure_analysis(prompt, max_tokens=150)

            if response_text:
                clean_text = response_text.replace("\n", " ").replace("  ", " ")
                
                # CORTE RÍGIDO DO USUÁRIO (350 caracteres)
                if len(clean_text) > 350:
                    clean_text = clean_text[:350]
                    last_space = clean_text.rfind(" ")
                    if last_space > 0:
                        clean_text = clean_text[:last_space] + "..."
                    else:
                        clean_text += "..."

                self.bot.send_message(channel, clean_text)
        
        except Exception as e:
            logging.error(f"[Analysis] Falha: {e}")
            self.bot.send_message(channel, "glorp **GL-0RP5:** Erro de compilação.")