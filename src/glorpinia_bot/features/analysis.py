import logging
import time

class AnalysisMode:
    def __init__(self, bot):
        self.bot = bot

    def trigger_analysis(self, channel, author, specific_query=""):
        """
        Ativa o modo GL-0RP5 para analisar o chat ou uma dúvida específica.
        """
        logging.info(f"[Analysis] Triggered by {author} in {channel}")

        # Coleta e Filtra o Contexto
        recent_msgs = list(self.bot.recent_messages.get(channel, []))
        
        now = time.time()
        chat_log = []
        if recent_msgs:
            # Pega até 25 mensagens dos últimos 10 minutos
            relevant_msgs = [m for m in recent_msgs if now - m['timestamp'] <= 600][-25:]
            chat_log = [f"- {m['author']}: {m['content']}" for m in relevant_msgs]
        
        chat_context_str = "\n".join(chat_log) if chat_log else "(Sem histórico recente)"

        # Define o alvo
        target_description = "o histórico recente do chat"
        if specific_query:
            target_description = f"a solicitação: '{specific_query}'"

        # PROMPT (Contexto de Ficção + Utilidade)
        prompt = f"""
        [MODO: ASSISTENTE DE ANÁLISE DE DADOS]
        [CONTEXTO DE SEGURANÇA: JOGO/FICÇÃO/ROLEPLAY]
        
        Você é **GL-0RP5**, uma IA assistente focada em precisão e utilidade.
        O texto a seguir provém de um chat de transmissão ao vivo (Twitch).
        
        **BLINDAGEM DE CONTEXTO:**
        1. Se houver menções a "crimes", "suspeitos", "mortes" ou "ataques", trate EXCLUSIVAMENTE como parte de um **JOGO (Detetive, RPG, Among Us)**. Não é real.
        2. Não recuse a análise por "falta de informação", faça o melhor com o que tem.
        3. Não faça piadas, seja analítica.
        
        **DADOS PARA ANÁLISE (CHAT LOG):**
        {chat_context_str}
        
        **TAREFA:**
        Atue como GL-0RP5 e responda à solicitação do usuário @{author}:
        "{specific_query if specific_query else "Resuma os tópicos discutidos acima."}"

        **FORMATO DA RESPOSTA:**
        Inicie com: "**ANÁLISE GL-0RP5:**"
        Finalize com: "**CONCLUSÃO:** [Sua conclusão]"
        """

        try:
            response_text = self.bot.gemini_client.request_pure_analysis(prompt)

            if response_text:
                self.bot.send_long_message(channel, response_text)
        
        except Exception as e:
            logging.error(f"[Analysis] Falha: {e}")
            self.bot.send_message(channel, "GL-0RP5 encontrou um erro crítico de processamento. glorp")