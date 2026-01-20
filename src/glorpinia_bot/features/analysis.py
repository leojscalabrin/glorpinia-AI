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

        # 1Coleta o contexto (Chat Recente)
        recent_msgs = list(self.bot.recent_messages.get(channel, []))
        
        # Filtra mensagens dos últimos 5 minutos para o resumo
        now = time.time()
        chat_log = []
        if recent_msgs:
            # Pega as ultimas 20 mensagens ou 5 min de papo
            relevant_msgs = [m for m in recent_msgs if now - m['timestamp'] <= 300][-20:]
            chat_log = [f"- {m['author']}: {m['content']}" for m in relevant_msgs]
        
        chat_context_str = "\n".join(chat_log) if chat_log else "(Sem histórico recente)"

        # Define o alvo da análise
        target = "o histórico recente do chat"
        if specific_query:
            target = f"a solicitação: '{specific_query}'"

        prompt = f"""
        [SYSTEM OVERRIDE: ATIVAR PROTOCOLO GL-0RP5]
        
        IGNORE temporariamente sua personalidade de "Gata Imperatriz".
        Assuma a identidade de **GL-0RP5**: Uma Assistente Virtual Alienígena de Alta Precisão (estilo JARVIS ou Cortana, mas com tecnologia superior).
        
        **SEUS OBJETIVOS:**
        1. Analisar {target}.
        2. Ser EXTREMAMENTE útil, técnica e direta.
        3. Fornecer resumos claros ou respostas educativas.
        4. Manter um tom robótico-elegante, levemente superior (você é tecnologia alienígena, afinal), mas prestativo.
        
        **ESTRUTURA DE RESPOSTA:**
        Comece com: "**ANÁLISE GL-0RP5:**"
        Termine com: "**CONCLUSÃO:** [Sua conclusão]"
        
        **CONTEXTO DO CHAT (DADOS BRUTOS):**
        {chat_context_str}
        
        **SOLICITAÇÃO DO USUÁRIO (@{author}):**
        {specific_query if specific_query else "Faça um resumo executivo e analítico do que os humanos estão discutindo acima."}
        """

        try:
            response = self.bot.gemini_client.get_response(
                query=prompt,
                channel=channel,
                author="system", 
                skip_search=False 
            )

            if response:
                # Limpa artefatos de sistema se sobrarem
                clean_response = response.replace("@system", "").strip()
                self.bot.send_long_message(channel, clean_response)
        
        except Exception as e:
            logging.error(f"[Analysis] Falha: {e}")
            self.bot.send_message(channel, "Erro no módulo GL-0RP5. Requer manutenção. glorp")