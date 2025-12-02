import time
import logging
import json
from datetime import datetime

class TrainingLogger:
    def __init__(self, bot):
        """
        Inicializa o logger já no formato Vertex AI.
        """
        print("[Feature] TrainingLogger Initialized (Vertex AI Mode).")
        self.bot = bot
        # Cache para evitar spam de logs no console
        self.last_logged_content = {} 

    def log_interaction(self, channel, author, user_message, bot_response):
        """
        Salva a interação no formato específico do Google Vertex AI:
        {"contents": [{"role": "user", "parts": [...]}, {"role": "model", "parts": [...]}]}
        """
        # Se não houver resposta, ignora
        if not bot_response:
            return

        try:
            # Obtém o System Prompt atual (Personalidade)
            # Acessa via self.bot -> self.auth -> personality_profile
            system_instruction = getattr(self.bot.auth, 'personality_profile', "")
            
            # Realiza a "Fusão" (System Prompt + User Message)
            if system_instruction:
                full_input = f"{system_instruction}\n\n---\n\n{user_message}"
            else:
                full_input = user_message

            # Monta a estrutura JSON exata do Vertex
            record = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": full_input}]
                    },
                    {
                        "role": "model",
                        "parts": [{"text": bot_response}]
                    }
                ]
            }

            # Salva no arquivo
            json_record = json.dumps(record, ensure_ascii=False)
            
            with open("training_data.jsonl", "a", encoding="utf-8") as f:
                f.write(f"{json_record}\n")
            
            # Log visual no console
            last_log_time = self.last_logged_content.get(channel, 0)
            if time.time() - last_log_time > 60:
                logging.info(f"[TrainingLogger] Novo dado de treino salvo (Vertex Format).")
                self.last_logged_content[channel] = time.time()

        except Exception as e:
            logging.error(f"[TrainingLogger] Falha ao escrever log Vertex: {e}")