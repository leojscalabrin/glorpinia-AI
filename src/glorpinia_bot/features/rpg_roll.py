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
        
        # Determina o status do resultado para guiar a IA
        if d20_result == 20:
            status = "SUCESSO CRÍTICO (NAT 20) - Feito Lendário/Divino"
            emoji = "🔥🐲"
        elif d20_result == 1:
            status = "FALHA CRÍTICA (NAT 1) - Desastre Humilhante/Cômico"
            emoji = "💀🤡"
        elif d20_result >= 10:
            status = "Sucesso - O herói conseguiu"
            emoji = "⚔️"
        else:
            status = "Falha - O herói tentou e falhou"
            emoji = "🍃"

        context_str = ""
        if not action_query:
            recent_msgs = list(self.bot.recent_messages.get(channel, []))
            now = time.time()
            if recent_msgs:
                relevant_msgs = [m for m in recent_msgs if now - m['timestamp'] <= 300][-5:]
                chat_log = [f"- {m['author']}: {m['content']}" for m in relevant_msgs]
                context_str = "\n".join(chat_log)
                action_query = "Realizar uma ação baseada no contexto atual da conversa."
        
        prompt = f"""
        [MODO: GLORIANA (A BARDA / MESTRE DE RPG)]
        [AMBIENTE: TAVERNA MEDIEVAL / FANTASIA]

        **O JOGADOR:** @{author}
        **A AÇÃO TENTADA:** "{action_query}"
        **RESULTADO DO DADO (D20):** {d20_result}
        **VEREDITO DO DESTINO:** {status}

        **CONTEXTO RECENTE (OPCIONAL):**
        {context_str}

        **SUA TAREFA:**
        Como Gloriana, a Barda, narre o resultado dessa rolagem.
        1. **SE FOI 20:** Narre um feito épico, exagerado, quase divino.
        2. **SE FOI 1:** Narre um desastre engraçado (tropeçou, quebrou o alaúde, o monstro riu).
        3. **NORMAL:** Narre a ação dando certo ou errado de forma dramática.

        **PERSONALIDADE:** - Você toca um alaúde desafinado.
        - Tente fazer uma rima ruim ou usar palavras arcaicas ("Vós", "Deveras", "Maldito Goblin").
        - Trate o chat como uma Taverna.

        **REGRAS:**
        - Resposta CURTA (Máx 250 caracteres).
        - NÃO explique as regras, vá direto para a narração.
        - Use emojis de RPG.

        **RESPOSTA GLORIANA:**
        """

        try:
            narrative = self.bot.gemini_client.request_rpg_narration(prompt)
            
            narrative = narrative.replace("\n", " ").strip()
            if len(narrative) > 380:
                narrative = narrative[:380] + "..."

            # Monta a mensagem final: Resultado Numérico + Narração
            final_msg = f"🎲 **{d20_result}** {emoji} | {narrative}"
            
            self.bot.send_message(channel, final_msg)

        except Exception as e:
            logging.error(f"[RPG] Erro: {e}")
            self.bot.send_message(channel, f"🎲 **{d20_result}** | *Gloriana derrubou o alaúde e não conseguiu narrar.* (Erro de sistema)")