import threading
import logging
from datetime import date

class FortuneCookie:
    def __init__(self, bot):
        """
        Inicializa a feature Fortune Cookie.
        'bot' é a instância principal do TwitchIRC.
        """
        print("[Feature] FortuneCookie Initialized.")
        self.bot = bot
        # Dicionário para rastrear o último dia que um usuário pegou um cookie
        # Formato: {"username": date(2025, 11, 5)}
        self.cooldowns = {}

    def get_fortune(self, channel: str, author: str):
        """
        Verifica o cooldown e, se liberado, gera uma 'sorte' em um thread.
        Isso é chamado pelo on_message.
        """
        
        today = date.today()
        last_cookie_date = self.cooldowns.get(author.lower())

        if last_cookie_date == today:
            # Usuário já pegou um hoje. Envia mensagem de cooldown.
            logging.info(f"[FortuneCookie] Cooldown ativo para {author}.")
            self.bot.send_message(channel, f"@{author}, você já pegou seu biscoito da sorte hoje! Madge Guloso")
            return
        
        # Se chegou aqui, o usuário pode pegar um cookie
        # Atualiza o cooldown antes de iniciar o thread
        self.cooldowns[author.lower()] = today

        # Roda a lógica da API em um thread
        t = threading.Thread(target=self._generate_fortune_thread, 
                             args=(channel, author))
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
        personalidade da Glorpinia.
        
        Pode ser um bom conselho, um aviso vago, ou uma piada alienígena 
        sarcástica (como se viesse de Meowdromeda).
        
        Comece sua resposta com 'glorp 🥠'.
        """

    def _generate_fortune_thread(self, channel: str, author: str):
        """
        Lógica real que chama a API (roda no thread).
        """
        try:
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
                # O gemini_client já formata com o @autor
                self.bot.send_long_message(channel, response)
            else:
                self.bot.send_message(channel, f"@{author}, o biscoito da sorte veio... vazio. Sadge")
        
        except Exception as e:
            logging.error(f"[FortuneCookie] Falha ao gerar sorte: {e}")
            self.bot.send_message(channel, f"@{author}, o portal está instável. Sadge")