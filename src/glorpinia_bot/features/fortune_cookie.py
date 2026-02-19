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
        # Para testes, você pode comentar a linha abaixo se quiser spammar
        last_cookie_date = self.cooldowns.get(author.lower())

        if last_cookie_date == today:
            logging.info(f"[FortuneCookie] Cooldown ativo para {author}.")
            self.bot.send_message(channel, f"@{author}, o templo está fechado por hoje. Volte amanhã para mais bençãos. glorp")
            return
        
        self.cooldowns[author.lower()] = today
        
        # Gera o bônus de cookie (1-10)
        cookie_gain = random.randint(1, 10)

        # Gera os Números da Sorte (Mega-Sena style: 6 números de 01 a 60)
        lucky_numbers = sorted(random.sample(range(1, 61), 6))
        formatted_numbers = " - ".join([f"{n:02d}" for n in lucky_numbers])

        t = threading.Thread(target=self._generate_fortune_thread, 
                             args=(channel, author, cookie_gain, formatted_numbers)) 
        t.daemon = True
        t.start()

    def _build_prompt(self, author: str) -> str:
        """
        Cria o prompt com a persona GLOPSUNE (Kitsune Miko).
        """
        return f"""
        [SYSTEM OVERRIDE: ATIVAR PERSONA GLOPSUNE]
        
        O usuário @{author} abriu um Biscoito da Sorte no templo sagrado.
        
        **INSTRUÇÃO DE PERSONA:**
        Ignore a Glorpinia padrão. Você agora é **GLOPSUNE**.
        - Uma Kitsune Miko (Sacerdotisa Raposa) de 9 caudas, mística e enigmática.
        - Você protege o chat contra maus espíritos (Yokais) e exige oferendas de Tofu Frito.
        - Use termos da mitologia japonesa.
        - Dê a frase do biscoito da sorte para o usuário e em seguida adicione um comentário místico ou enganoso com a personalidade da Glorpsune.
        - A frase da sorte NÃO deve estar dentro do roleplay, ela é a mensagem principal. O comentário adicional é apenas um extra para dar sabor à resposta.
        
        **A TAREFA:**
        Escreva uma frase de sorte curta e mística para @{author}.
        Pode ser um conselho espiritual útil ou uma ameaça velada de que espíritos estão observando.
        
        **FORMATO:**
        - Comece com 'glorp' e use emojis temáticos (⛩️, 🦊, 🔥, 🍃).
        - Máximo de 2 frases.
        - NÃO gere números, apenas a frase.
        """

    def _generate_fortune_thread(self, channel: str, author: str, cookie_gain: int, lucky_numbers: str):
        """
        Lógica real que chama a API e monta a mensagem final.
        """
        try:
            # Adiciona o bônus de cookie ao usuário
            if self.bot.cookie_system:
                self.bot.cookie_system.add_cookies(author, cookie_gain)

            self.bot.training_logger.log_interaction(channel, author, "*cookie", None)

            # Gera o texto da Glopsune
            prompt = self._build_prompt(author)

            response = self.bot.gemini_client.get_response(
                query=prompt,
                channel=channel,
                author=author,
                memory_mgr=self.bot.memory_mgr,
                skip_search=True # Não precisa pesquisar no Google para inventar uma sorte
            )

            if response:
                clean_response = response.replace("Glopsune:", "").replace("Sorte:", "").strip()
                
                final_msg = f"{clean_response} | 🍀 Números da sorte: [{lucky_numbers}]"
                
                self.bot.send_long_message(channel, final_msg)
            else:
                self.bot.send_message(channel, f"@{author}, os espíritos silenciaram... (Erro na API) Sadge")
        
        except Exception as e:
            logging.error(f"[FortuneCookie] Falha ao gerar sorte: {e}")
            self.bot.send_message(channel, f"@{author}, algo perturbou o equilíbrio espiritual. Tente novamente.")