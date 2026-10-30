import re
import threading
import logging
from datetime import date
import random

# Separadores que o modelo costuma usar entre a frase do biscoito e um comentário ("frase - comentário").
_COMMENT_SEPARATOR = re.compile(r"\s[-–—]\s")

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
        formatted_numbers = self._format_lucky_numbers(lucky_numbers)

        t = threading.Thread(target=self._generate_fortune_thread, 
                             args=(channel, author, cookie_gain, formatted_numbers)) 
        t.daemon = True
        t.start()

    @staticmethod
    def _format_lucky_numbers(numbers) -> str:
        """Números da sorte colados por hífen, sem espaços: 01-02-13-41-55-60."""
        return "-".join(f"{n:02d}" for n in numbers)

    @staticmethod
    def _format_cookie_gain(amount: int) -> str:
        """Texto do ganho exibido ao usuário, no formato padrão do bot: '+4🍪'."""
        return f"+{amount}🍪"

    @staticmethod
    def _strip_comment(text: str) -> str:
        """Rede de segurança: remove qualquer comentário depois da frase ("frase - comentário").

        O prompt já proíbe esse separador dentro da frase, então tudo após ele é comentário.
        """
        parts = _COMMENT_SEPARATOR.split(text, maxsplit=1)
        head = parts[0].strip()
        return head if head else text.strip()

    def _build_prompt(self, author: str) -> str:
        """
        Cria o prompt do biscoito da sorte: apenas a frase, sem comentário.
        """
        return f"""
        O usuário @{author} abriu um Biscoito da Sorte no Torii Sagrado.
        
        **A MENSAGEM DO BISCOITO (O Provérbio)**
        Escreva uma frase que pareça ter saído de um biscoito da sorte real. 
        - Deve ser curta, enigmática e proverbial.
        - Use metáforas
        - É apenas a sabedoria do papelzinho: sem comentário, explicação, assinatura ou observação depois da frase.

        **REGRAS DE FORMATO:**
        1. Comece a resposta com 'glorp' e emojis (⛩️, 🦊, 🔥).
        2. Formato: apenas "[FRASE DO BISCOITO]". NÃO adicione nada depois da frase.
        3. NÃO use hífen com espaços ( - ) nem travessão dentro da frase.
        4. Máximo de 250 caracteres no total.
        5. NÃO gere números de sorte.

        Sua resposta para @{author}:
        """

    def _generate_fortune_thread(self, channel: str, author: str, cookie_gain: int, lucky_numbers: str):
        """
        Lógica real que chama a API e monta a mensagem final.
        """
        try:
            # Adiciona o bônus de cookie ao usuário. Só mostra o ganho se o crédito foi confirmado.
            gain_text = None
            if self.bot.cookie_system and self.bot.cookie_system.add_cookies(author, cookie_gain, award_xp=True):
                gain_text = self._format_cookie_gain(cookie_gain)

            self.bot.training_logger.log_interaction(channel, author, "*cookie", None)

            # Gera o texto da Glopsune
            prompt = self._build_prompt(author)

            response = self.bot.gemini_client.get_response(
                query=prompt,
                channel=channel,
                author=author,
                memory_mgr=self.bot.memory_mgr,
                skip_search=True, # Não precisa pesquisar no Google para inventar uma sorte
                live_context=self.bot.get_live_context(channel)
            )

            if response:
                clean_response = self._strip_comment(response.replace("Glopsune:", "").replace("Sorte:", "").strip())
                
                final_msg = f"{clean_response} | 🍀 Números da sorte: [{lucky_numbers}]"
                if gain_text:
                    final_msg += f" | {gain_text}"
                
                self.bot.send_long_message(channel, final_msg)
            else:
                error_msg = f"@{author}, os espíritos silenciaram... (Erro na API) Sadge"
                if gain_text:
                    # Os cookies já foram creditados antes da chamada à IA; avisa para não ganhar em silêncio.
                    error_msg += f" | {gain_text}"
                self.bot.send_message(channel, error_msg)
        
        except Exception as e:
            logging.error(f"[FortuneCookie] Falha ao gerar sorte: {e}")
            self.bot.send_message(channel, f"@{author}, algo perturbou o equilíbrio espiritual. Tente novamente.")