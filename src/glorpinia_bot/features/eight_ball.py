import threading
import logging

class EightBall:
    def __init__(self, bot):
        """
        Inicializa a feature 8-Ball.
        'bot' é a instância principal do TwitchIRC.
        """
        print("[Feature] EightBall Initialized.")
        self.bot = bot

    def get_8ball_response(self, question: str, channel: str, author: str):
        """
        Gera uma resposta da 8-Ball em um thread.
        Isso é chamado pelo on_message.
        """
        # Roda a lógica da API em um thread para não travar o bot
        t = threading.Thread(target=self._generate_response_thread, 
                             args=(question, channel, author))
        t.daemon = True
        t.start()

    def _build_prompt(self, question: str) -> str:
        """
        Cria o "meta-prompt" que força o Gemini a agir como uma 8-Ball
        mantendo a personalidade da Glorpinia.
        """
        return f"""
        [MODO 8-BALL ATIVADO]
        O usuário @{question['author']} perguntou: "{question['text']}"
        
        Sua missão é responder a esta pergunta como uma 'Magic 8-Ball' mística.
        Você DEVE dar uma resposta curta e vaga em uma das três categorias:
        1. Afirmativa (ex: Sim, Com certeza, glorp SIM)
        2. Não-Comprometida (ex: Pergunte mais tarde, Talvez, Não sei bicho)
        3. Negativa (ex: Não, Nem pensar, Minhas anteninhas dizem não)

        Mantenha sua personalidade de Glorpinia, mas seja misteriosa. 
        Comece sua resposta com 'glorp'.
        """

    def _generate_response_thread(self, question_text: str, channel: str, author: str):
        """
        Lógica real que chama a API (roda no thread).
        """
        try:
            # Loga a pergunta do usuário
            self.bot.training_logger.log_interaction(channel, author, f"!glorp 8ball {question_text}", None)

            # Constrói a pergunta e o prompt
            question_data = {"author": author, "text": question_text}
            prompt = self._build_prompt(question_data)

            # Chama o Gemini
            response = self.bot.gemini_client.get_response(
                query=prompt,
                channel=channel,
                author=author,
                memory_mgr=self.bot.memory_mgr
            )

            # Envia a resposta
            if response:
                self.bot.send_long_message(channel, response)
            else:
                self.bot.send_message(channel, f"@{author}, minhas anteninhas estão com interferência. Tente de novo. Sadge")
        
        except Exception as e:
            logging.error(f"[EightBall] Falha ao gerar resposta 8-Ball: {e}")
            self.bot.send_message(channel, f"@{author}, o portal está instável. Sadge")