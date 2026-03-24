import time
import threading
import logging
import random
import re

class Comment:
    DRAMA_ROLEPLAY_MENTION_PROBABILITY = 0.35
    COMMENT_IMPERIAL_TAX_PROBABILITY = 0.18
    COMMENT_IMPERIAL_TAX_MIN = 5
    COMMENT_IMPERIAL_TAX_MAX = 18

    def __init__(self, bot):
        """
        Inicializa a feature de comentários periódicos.
        'bot' é a instância principal do TwitchIRC.
        """
        print("[Feature] Comment Initialized.")
        self.bot = bot
        self.enabled = False
        
        self.last_comment_time = 0
        self.COOLDOWN_SECONDS = 1200

    def set_enabled(self, state: bool):
        """Ativa ou desativa esta feature."""
        self.enabled = state
        if not state:
            logging.info("[Comment] Desativado.")

    def get_status(self):
        """Retorna o status formatado para o comando *check."""
        status = "ATIVADO" if self.enabled else "DESATIVADO"
        return f"{status}"

    def stop_thread(self):
        """Função mantida (chamada pelo main) mas não faz mais nada."""
        pass

    def roll_for_comment(self, channel: str, author: str):
        """
        Chamado a CADA MENSAGEM. Rola um dado para ver se o bot comenta.
        Se acionado, o autor da mensagem ganha 10 cookies.
        """
        if not self.enabled:
            return

        # VERIFICAÇÃO DE COOLDOWN
        # Se ainda não passou 20 minutos desde o último comentário, ignora.
        if (time.time() - self.last_comment_time) < self.COOLDOWN_SECONDS:
            return 
        
        # Chance fixa de 1%
        if random.random() < 0.01:
            logging.info(f"[Comment] Gatilho atingido por {author}!")
            logging.debug("[Comment] roll acionado channel=%s author=%s", channel, author)
            
            # Atualiza o timer para evitar disparos duplos
            self.last_comment_time = time.time()
            
            # Premiação (Cookies)
            if self.bot.cookie_system:
                self.bot.cookie_system.add_cookies(author, 10)
                logging.info(f"[Comment] {author} ganhou 10 cookies pelo trigger!")
            
            # Coleta de Contexto
            now = time.time()
            recent_msgs = self.bot.recent_messages.get(channel, None)
            
            if not recent_msgs:
                return

            # Pega mensagens dos últimos 2 minutos (120s)
            recent_context = [msg for msg in recent_msgs if now - msg['timestamp'] <= 120]
            
            # Se tiver muito pouca conversa, pula e não comenta
            if len(recent_context) < 3: 
                logging.debug(f"[Comment] Gatilho atingido, mas poucas mensagens recentes. Pulando.")
                return
            
            context_str = "\n".join([f"{msg['author']}: {msg['content']}" for msg in recent_context])
            logging.debug("[Comment] recent_context_count=%s", len(recent_context))
            
            # Extrai lista de usuários únicos ativos para passar ao prompt
            active_users = list(set([msg['author'] for msg in recent_context]))

            # Dispara a thread de geração
            t = threading.Thread(target=self._generate_comment_thread, 
                                 args=(context_str, channel, self.bot.memory_mgr, active_users))
            t.daemon = True
            t.start()
            
    
    def _generate_comment_thread(self, context_str: str, channel: str, memory_mgr, active_users: list):
        """
        Thread que chama a IA (2 passagens), para não travar a 'on_message'.
        """
        try:
            # Sumarizar o log do chat
            topic = self.bot.gemini_client.summarize_chat_topic(context_str)

            if not topic or topic == "assuntos aleatórios":
                return

            # Formata a lista de usuários para o prompt
            users_str = ", ".join(active_users)

            drama_roleplay_hint = self._build_drama_roleplay_hint(channel)
            tax_context = self._maybe_apply_comment_imperial_tax(channel, active_users)

            comment_query = (
                f"O chat está falando sobre: '{topic}'. "
                f"Faça um comentário curto (1-2 frases), divertido e com sua personalidade sobre esse assunto. "
                f"Use estritamente os Emotes da sua lista (não invente emotes).\n\n"
                f"Se quiser usar o sistema de Cookies para punir ou premiar alguém por uma opinião no contexto, "
                f"os ÚNICOS usuários válidos presentes agora são: [{users_str}]. "
                f"NÃO use cookies em 'user', 'system' ou pessoas fora dessa lista. "
                f"Se usar cookie, emita somente a tag [[COOKIE:...]] no final, sem explicar o comando."
            )

            if drama_roleplay_hint:
                comment_query += f"\n\n{drama_roleplay_hint}"

            if tax_context:
                comment_query += (
                    "\n\n"
                    f"Imposto imperial já executado antes desta resposta: {tax_context}. "
                    "Mencione o imposto no seu comentário, de forma curta e teatral."
                )

            injection_context = self.bot.social_dynamics.get_injection_payload(channel)
            comment = self.bot.gemini_client.get_response(
                query=comment_query,
                channel=channel,
                author="system",
                memory_mgr=memory_mgr,
                skip_search=True,
                allow_cookie_actions=True,
                injection_context=injection_context,
            )

            if 0 < len(comment) <= 350:
                final_message = (comment or "").replace("@system, ", "")
                if self.bot.cookie_system:
                    final_message = self.bot.cookie_system.strip_cookie_commands(final_message)
                else:
                    final_message = re.sub(r"\[\[COOKIE:[^\]]*\]\]", "", final_message, flags=re.IGNORECASE).strip()
                if not final_message:
                    return
                formatted_message = self.bot.prepare_final_bot_message(
                    channel,
                    final_message,
                    source="comment",
                    context_text=f"{topic} {context_str}",
                )
                self.bot.send_message(channel, formatted_message)
                logging.debug(f"[Comment] Comentario enviado em {channel}: {final_message[:80]}...")
        except Exception as e:
            logging.error(f"[Comment] Falha ao gerar comentario: {e}")

    def _build_drama_roleplay_hint(self, channel: str):
        if random.random() >= self.DRAMA_ROLEPLAY_MENTION_PROBABILITY:
            return None

        drama_state = self.bot.social_dynamics.get_debug_snapshot(channel).get("drama_state", {})
        if not drama_state:
            return None

        candidates = []
        favorite = (drama_state.get("favorite_of_the_day") or "").strip()
        enemy = (drama_state.get("enemy_of_the_day") or "").strip()
        suspect = (drama_state.get("suspect") or "").strip()
        rivalries = [r for r in drama_state.get("rivalries", []) if isinstance(r, str) and r.strip()]

        if favorite:
            candidates.append(
                f"Se fizer sentido no assunto, mencione de forma curta e teatral que @{favorite} virou seu queridinho do momento."
            )
        if enemy:
            candidates.append(
                f"Se combinar com o contexto, faça uma provocação breve dizendo que @{enemy} está na sua lista de desafetos hoje."
            )
        if suspect:
            candidates.append(
                f"Se houver gancho no papo, solte uma suspeita dramática em 1 frase sobre @{suspect}."
            )
        if rivalries:
            rivalry = random.choice(rivalries)
            if " vs " in rivalry:
                left, right = [part.strip() for part in rivalry.split(" vs ", 1)]
                if left and right:
                    candidates.append(
                        f"Se encaixar, provoque uma rivalidade curtinha entre @{left} e @{right} em tom de fofoca imperial."
                    )

        if not candidates:
            return None

        return random.choice(candidates)

    def _maybe_apply_comment_imperial_tax(self, channel: str, active_users: list):
        if random.random() >= self.COMMENT_IMPERIAL_TAX_PROBABILITY:
            return None

        if not self.bot.cookie_system:
            return None

        eligible_users = []
        for user in active_users:
            user_lower = (user or "").strip().lower()
            if not user_lower:
                continue
            if user_lower in {"system", "user", "usuario", self.bot.auth.bot_nick.lower()}:
                continue
            eligible_users.append(user_lower)

        if not eligible_users:
            return None

        target_user = random.choice(eligible_users)
        tax_amount = random.randint(self.COMMENT_IMPERIAL_TAX_MIN, self.COMMENT_IMPERIAL_TAX_MAX)
        self.bot.cookie_system.remove_cookies(target_user, tax_amount)
        logging.info(
            "[Comment] imposto imperial via comment_trigger channel=%s target=%s amount=%s",
            channel,
            target_user,
            tax_amount,
        )
        return f"@{target_user} perdeu {tax_amount} cookies"
