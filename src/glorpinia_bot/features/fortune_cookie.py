import threading
import logging
from datetime import date
import random

class FortuneCookie:
    def __init__(self, bot):
        """
        Inicializa a feature Fortune Cookie.
        'bot' é a instância principal do TwitchIRC.
        """
        print("[Feature] FortuneCookie Initialized.")
        self.bot = bot
        self.cooldowns = {}

    def get_fortune(self, channel: str, author: str):
        """
        Verifica o cooldown e, se liberado, gera uma 'sorte' e cookies.
        """
        
        today = date.today()
        last_cookie_date = self.cooldowns.get(author.lower())

        if last_cookie_date == today:
            logging.info(f"[FortuneCookie] Cooldown ativo para {author}.")
            self.bot.send_message(channel, f"@{author}, você já pegou seu biscoito da sorte hoje! Tente amanhã. glorp")
            return
        
        self.cooldowns[author.lower()] = today
        
        # Gera o bônus de cookie (1-10) e o passa para o thread.
        cookie_gain = random.randint(1, 10)

        t = threading.Thread(target=self._generate_fortune_thread, 
                             args=(channel, author, cookie_gain)) # <- Passa o bônus
        t.daemon = True
        t.start()

    def _build_prompt(self, author: str) -> str:
        """
        Cria o "meta-prompt" que força o Gemini a agir como um Biscoito
        da Sorte, mantendo a personalidade da Glorpinia.
        """
        return f"""
        [MODO BISCOITO DA SORTE ATIVADO]
        O usuário @{author} acabou de pedir um biscoito da sorte.

        Sua missão é dar a ele uma "sorte" (fortune).
        A sorte deve ser curta (1-2 frases), misteriosa, e ter a 
        personalidade da Glorpinia, ignore sua memória.
        
        Pode ser um bom conselho, um aviso vago, ou uma piada alienígena 
        sarcástica (como se viesse de Meowdromeda).
        
        Comece sua resposta com 'glorp'.
        """

    def _generate_fortune_thread(self, channel: str, author: str, cookie_gain: int): # <- Recebe o bônus
        """
        Lógica real que chama a API (roda no thread).
        """
        try:
            # Adiciona o bônus de cookie ao usuário
            if self.bot.cookie_system:
                self.bot.cookie_system.add_cookies(author, cookie_gain)

            # Loga a pergunta do usuário
            self.bot.training_logger.log_interaction(channel, author, "!glorp cookie", None)

            # Constrói o prompt
            prompt = self._build_prompt(author)

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
                self.bot.send_message(channel, f"@{author}, o biscoito da sorte veio... vazio. Sadge")
        
        except Exception as e:
            logging.error(f"[FortuneCookie] Falha ao gerar sorte: {e}")
            self.bot.send_message(channel, f"@{author}, o portal está instável. Sadge")