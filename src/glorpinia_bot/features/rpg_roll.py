import logging
import random
import time

class RPGRollFeature:
    def __init__(self, bot):
        self.bot = bot

    def trigger_roll(self, channel, author, action_query=""):
        """
        Rola um D20 e gera uma narração épica da Gloriana.
        """
        logging.info(f"[RPG] Roll requested by {author} in {channel}")

        d20_result = random.randint(1, 20)
        
        if d20_result == 20:
            status = "SUCESSO CRÍTICO (NAT 20) - Feito Lendário"
            emoji = "🔥🐲"
        elif d20_result == 1:
            status = "FALHA CRÍTICA (NAT 1) - Desastre Cômico"
            emoji = "💀🤡"
        elif d20_result >= 10:
            status = "Sucesso"
            emoji = "⚔️"
        else:
            status = "Falha"
            emoji = "🍃"

        # Contexto
        context_str = ""
        if not action_query:
            recent_msgs = list(self.bot.recent_messages.get(channel, []))
            now = time.time()
            if recent_msgs:
                relevant_msgs = [m for m in recent_msgs if now - m['timestamp'] <= 300][-5:]
                chat_log = [f"- {m['author']}: {m['content']}" for m in relevant_msgs]
                context_str = "\n".join(chat_log)
                action_query = "Realizar uma ação baseada no contexto atual."
        
        # Prompt
        prompt = f"""
        [MODO: GLORIANA (A BARDA)]
        [CONTEXTO: TAVERNA RPG / HUMOR]

        **JOGADOR:** @{author}
        **AÇÃO:** "{action_query}"
        **DADO:** {d20_result} ({status})

        **CONTEXTO CHAT (OPCIONAL):**
        {context_str}

        **SUA TAREFA:**
        Narre o resultado desta ação como Gloriana.
        - Se foi 20: Épico e exagerado.
        - Se foi 1: Desastre engraçado.
        - Usar linguagem arcaica
        - Equilibrar entre 20 e 1 para sucesso e falha normais.
        - Incluir humor leve e referências medievais.
        - Ser breve: máximo 3 a 4 frases.
        
        **RESPOSTA GLORIANA:**
        """

        try:
            narrative = self.bot.gemini_client.request_rpg_narration(prompt)
            
            # Limpeza
            clean_text = narrative.replace("\n", " ").replace("  ", " ").strip()

            MAX_CHARS = 350
            if len(clean_text) > MAX_CHARS:
                cut_text = clean_text[:MAX_CHARS]
                last_space = cut_text.rfind(" ")
                if last_space > 0:
                    clean_text = cut_text[:last_space] + "..."
                else:
                    clean_text = cut_text + "..."

            final_msg = f"🎲 **{d20_result}** {emoji} | {clean_text}"
            self.bot.send_message(channel, final_msg)

        except Exception as e:
            logging.error(f"[RPG] Erro: {e}")
            self.bot.send_message(channel, f"🎲 **{d20_result}** | *A barda engasgou com hidromel.*")