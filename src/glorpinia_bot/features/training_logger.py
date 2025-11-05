import time
import logging
from datetime import datetime

class TrainingLogger:
    def __init__(self, bot):
        """
        Inicializa o logger de interações para fine-tuning.
        """
        print("[Feature] TrainingLogger Initialized.")
        self.bot = bot
        # Cache para evitar spam de logs
        self.last_logged_content = {} 

    def log_interaction(self, channel, author, user_message, bot_response):
        """
        Salva um registro de interação em formato JSONL.
        """
        record = {
            "timestamp": datetime.utcnow().isoformat(),
            "channel": channel,
            "author": author,
            "user_message": user_message,
            "bot_response": bot_response
        }
        try:
            with open("training_data.jsonl", "a", encoding="utf-8") as f:
                f.write(f"{str(record)}\n")
            
            last_log_time = self.last_logged_content.get(channel, 0)
            if time.time() - last_log_time > 60:
                logging.info(f"[TrainingLogger] Registro salvo para: {user_message[:30]}...")
                self.last_logged_content[channel] = time.time()
        except Exception as e:
            logging.error(f"[TrainingLogger] Falha ao escrever no arquivo de treinamento: {e}")