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
        self.enabled = False

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

    def roll_for_comment(self, channel: str):
        """
        Chamado a CADA MENSAGEM. Rola um dado para ver se o bot comenta.
        A lógica de "comentar sobre os últimos 2 minutos" é mantida.
        """
        # Se a feature estiver desligada, não faz nada.
        if not self.enabled:
            return

        # Rola o dado com uma chance fixa de 2%
        if random.random() < 0.02:
            logging.info(f"[Comment] Gatilho atingido! (Chance fixa de 2%)")
            
            # Removemos o reset da chance, pois não é mais necessário
            
            # Pega os últimos 2 minutos de mensagens (lógica antiga)
            now = time.time()
            recent_msgs = self.bot.recent_messages.get(channel, None)
            if not recent_msgs:
                return

            recent_context = [msg for msg in recent_msgs if now - msg['timestamp'] <= 120]
            
            if len(recent_context) < 3: # Não comenta se houver menos de 3 msgs
                logging.debug(f"[Comment] Gatilho atingido, mas poucas mensagens. Pulando.")
                return
            
            context_str = "\n".join([f"{msg['author']}: {msg['content']}" for msg in recent_context])
            comment_query = f"Comente de forma natural e divertida sobre essa conversa recente no chat da live: {context_str[:500]}..."
            
            # Roda a geração da IA em um thread para não travar
            t = threading.Thread(target=self._generate_comment_thread, 
                                 args=(comment_query, channel, self.bot.memory_mgr))
            t.daemon = True
            t.start()
            
    
    def _generate_comment_thread(self, query, channel, memory_mgr):
        """
        Thread que chama a IA, para não travar a 'on_message'.
        """
        try:
            comment = self.bot.gemini_client.get_response(
                query=query,
                channel=channel,
                author="system",
                memory_mgr=memory_mgr
            )
            if 0 < len(comment) <= 200:
                self.bot.send_message(channel, comment)
                logging.debug(f"[Comment] Comentario enviado em {channel}: {comment[:50]}...")
        except Exception as e:
            logging.error(f"[Comment] Falha ao gerar comentario: {e}")