import time
import threading
import logging
import random

class Comment:
    def __init__(self, bot):
        """
        Inicializa a feature de comentários periódicos.
        'bot' é a instância principal do TwitchIRC.
        """
        print("[Feature] Comment Initialized.")
        self.bot = bot
        self.enabled = True
        
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

            comment_query = (
                f"O chat está falando sobre: '{topic}'. "
                f"Faça um comentário curto (1-2 frases), divertido e com sua personalidade sobre esse assunto. "
                f"Use estritamente os Emotes da sua lista (não invente emotes).\n\n"
                f"Se quiser usar o sistema de Cookies para punir ou premiar alguém por uma opinião no contexto, "
                f"os ÚNICOS usuários válidos presentes agora são: [{users_str}]. "
                f"NÃO use cookies em 'user', 'system' ou pessoas fora dessa lista."
            )

            comment = self.bot.gemini_client.get_response(
                query=comment_query,
                channel=channel,
                author="system",
                memory_mgr=memory_mgr,
                skip_search=True
            )
            
            if 0 < len(comment) <= 350:
                if self.bot.cookie_system:
                    final_message = self.bot.cookie_system.process_ai_response(comment)
                else:
                    final_message = comment

                self.bot.send_message(channel, final_message)
                logging.debug(f"[Comment] Comentario enviado em {channel}: {final_message[:50]}...")
        except Exception as e:
            logging.error(f"[Comment] Falha ao gerar comentario: {e}")