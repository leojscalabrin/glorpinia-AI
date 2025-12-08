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

    def set_enabled(self, state: bool):
        """Ativa ou desativa esta feature."""
        self.enabled = state
        if not state:
            logging.info("[Comment] Desativado.")

    def get_status(self):
        """Retorna o status formatado para o comando !glorp check."""
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

        # Chance fixa de 2% (0.02)
        if random.random() < 0.02:
            logging.info(f"[Comment] Gatilho atingido por {author}!")
            
            if self.bot.cookie_system:
                self.bot.cookie_system.add_cookies(author, 10)
                logging.info(f"[Comment] {author} ganhou 10 cookies pelo trigger!")
            
            now = time.time()
            recent_msgs = self.bot.recent_messages.get(channel, None)
            if not recent_msgs:
                return

            recent_context = [msg for msg in recent_msgs if now - msg['timestamp'] <= 120]
            
            if len(recent_context) < 3: 
                logging.debug(f"[Comment] Gatilho atingido, mas poucas mensagens. Pulando.")
                return
            
            context_str = "\n".join([f"{msg['author']}: {msg['content']}" for msg in recent_context])
            
            t = threading.Thread(target=self._generate_comment_thread, 
                                 args=(context_str, channel, self.bot.memory_mgr))
            t.daemon = True
            t.start()
            
    
    def _generate_comment_thread(self, context_str: str, channel: str, memory_mgr):
        """
        Thread que chama a IA (2 passagens), para não travar a 'on_message'.
        """
        try:
            # 1. PASSAGEM 1: Sumarizar o log do chat
            topic = self.bot.gemini_client.summarize_chat_topic(context_str)

            if not topic or topic == "assuntos aleatórios":
                return

            # 2. PASSAGEM 2: Comentar sobre o tópico
            comment_query = f"O chat está falando sobre: '{topic}'. Faça um comentário curto (1-2 frases), divertido e com sua personalidade sobre esse assunto."

            comment = self.bot.gemini_client.get_response(
                query=comment_query,
                channel=channel,
                author="system",
                memory_mgr=memory_mgr,
                skip_search=True
            )
            
            if 0 < len(comment) <= 200:
                self.bot.send_message(channel, comment)
                logging.debug(f"[Comment] Comentario enviado em {channel}: {comment[:50]}...")
        except Exception as e:
            logging.error(f"[Comment] Falha ao gerar comentario: {e}")