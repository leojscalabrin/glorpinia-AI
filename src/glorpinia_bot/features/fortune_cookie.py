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
        
        O usuário @{author} abriu um Biscoito da Sorte no Torii Sagrado.
        
        **PARTE 1: A MENSAGEM DO BISCOITO (O Provérbio)**
        Escreva uma frase que pareça ter saído de um biscoito da sorte real. 
        - Deve ser curta, enigmática e proverbial.
        - Use metáforas
        - Não mencione a Glopsune aqui. É apenas a sabedoria do papelzinho.

        **PARTE 2: O COMENTÁRIO DA PERSONA (Glopsune)**
        Após a frase, adicione um comentário curto com a personalidade **GLOPSUNE**:
        - Ela é uma Kitsune Miko (Sacerdotisa Raposa) mística e sarcástica.
        - Ela deve comentar a sorte do usuário de forma enigmática, mencionando espíritos, oferendas de Tofu ou selos sagrados.
        - Exemplo: "...os espíritos riram dessa sua sorte. Onde está meu Tofu? glorp"

        **REGRAS DE FORMATO:**
        1. Comece a resposta com 'glorp' e emojis (⛩️, 🦊, 🔥).
        2. Formato: "[FRASE DO BISCOITO] - [COMENTÁRIO DA GLOPSUNE]"
        3. Máximo de 250 caracteres no total.
        4. NÃO gere números de sorte.

        Sua resposta para @{author}:
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