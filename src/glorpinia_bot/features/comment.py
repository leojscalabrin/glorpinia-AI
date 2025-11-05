import time
import threading
import logging

class Comment:
    def __init__(self, bot):
        """
        Inicializa a feature de comentários periódicos.
        'bot' é a instância principal do TwitchIRC.
        """
        print("[Feature] Comment Initialized.")
        self.bot = bot
        self.enabled = False
        self.last_comment_time = 0
        self.loop_sleep_interval = 10
        self.timer_running = True
        
        # Inicia o thread do timer
        self.thread = threading.Thread(target=self._periodic_thread, daemon=True)
        self.thread.start()

    def set_enabled(self, state: bool):
        """Ativa ou desativa esta feature."""
        self.enabled = state

    def get_status(self):
        """Retorna o status formatado para o comando !glorp check."""
        return "ATIVADO" if self.enabled else "DESATIVADO"

    def stop_thread(self):
        """Sinaliza para o thread parar (usado no shutdown)."""
        self.timer_running = False

    def _periodic_thread(self):
        """
        Thread em background: A cada 30 min, checa contexto e envia 
        comentario se aplicavel (se self.enabled for True).
        """
        self.last_comment_time = time.time()
        
        while self.timer_running:
            time.sleep(self.loop_sleep_interval)
            
            if not self.enabled:
                continue

            now = time.time()
            if now - self.last_comment_time < 1800:  # 30 minutos
                continue
            
            self.last_comment_time = now

            for channel in self.bot.auth.channels:
                recent_msgs = self.bot.recent_messages.get(channel, None)
                if not recent_msgs:
                    continue

                recent_context = [msg for msg in recent_msgs if now - msg['timestamp'] <= 120]
                
                if len(recent_context) == 0:
                    logging.debug(f"[Comment] Nenhuma mensagem recente em {channel}. Pulando.")
                    continue
                
                context_str = "\n".join([f"{msg['author']}: {msg['content']}" for msg in recent_context])
                
                comment_query = f"Comente de forma natural e divertida sobre essa conversa recente no chat da live: {context_str[:500]}..."
                
                try:
                    comment = self.bot.gemini_client.get_response(
                        query=comment_query,
                        channel=channel,
                        author="system",
                        memory_mgr=self.bot.memory_mgr
                    )
                    if 0 < len(comment) <= 200:
                        self.bot.send_message(channel, comment)
                        logging.debug(f"[Comment] Comentario enviado em {channel}: {comment[:50]}...")
                except Exception as e:
                    logging.error(f"[Comment] Falha ao gerar comentario: {e}")