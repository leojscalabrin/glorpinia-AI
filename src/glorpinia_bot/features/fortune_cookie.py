import re
import threading
import logging
from datetime import date
import random

from ..narrative.rpg_context import format_user_identity

# Separadores que o modelo costuma usar entre a frase do biscoito e um comentário.
_COMMENT_SEPARATOR = re.compile(r"\s[-–—]\s")
_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F1E0-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0000FE0F"
    "\U0000200D"
    "]",
    flags=re.UNICODE,
)


class FortuneCookie:
    def __init__(self, bot):
        """Inicializa a feature Fortune Cookie."""
        print("[Feature] FortuneCookie Initialized.")
        self.bot = bot
        self.cooldowns = {}

    def get_fortune(self, channel: str, author: str):
        """Verifica o cooldown e, se liberado, gera uma sorte e cookies."""
        today = date.today()
        last_cookie_date = self.cooldowns.get(author.lower())

        if last_cookie_date == today:
            logging.info("[FortuneCookie] Cooldown ativo para %s.", author)
            self.bot.send_message(
                channel,
                f"glorp @{author}, seu biscoito da sorte de hoje já foi aberto. Volte amanhã."
            )
            return

        self.cooldowns[author.lower()] = today

        cookie_gain = random.randint(1, 10)
        lucky_numbers = sorted(random.sample(range(1, 61), 6))
        formatted_numbers = self._format_lucky_numbers(lucky_numbers)

        t = threading.Thread(
            target=self._generate_fortune_thread,
            args=(channel, author, cookie_gain, formatted_numbers),
        )
        t.daemon = True
        t.start()

    @staticmethod
    def _format_lucky_numbers(numbers) -> str:
        """Números da sorte colados por hífen, sem espaços."""
        return "-".join(f"{n:02d}" for n in numbers)

    @staticmethod
    def _format_cookie_gain(amount: int) -> str:
        """Texto do ganho sem emojis."""
        return f"+{amount} cookies"

    @staticmethod
    def _strip_comment(text: str) -> str:
        """Remove qualquer comentário depois da frase principal."""
        parts = _COMMENT_SEPARATOR.split(text, maxsplit=1)
        head = parts[0].strip()
        return head if head else text.strip()

    @staticmethod
    def _clean_generated_text(text: str) -> str:
        """Remove prefixos duplicados, emojis e espaços indesejados."""
        clean = (text or "").replace("Glopsune:", "").replace("Sorte:", "").strip()
        clean = FortuneCookie._strip_comment(clean)
        clean = _EMOJI_PATTERN.sub("", clean)
        clean = re.sub(r"^(?:glorp\s*)+", "", clean, flags=re.IGNORECASE)
        return re.sub(r"\s+", " ", clean).strip()

    def _build_prompt(self, author: str) -> str:
        """Cria um prompt de biscoito da sorte variado e opcionalmente personalizado."""
        identity_context = format_user_identity(self.bot, author)

        return f"""
        @{author} está abrindo um biscoito da sorte.

        **A MENSAGEM DO BISCOITO**
        Escreva um único provérbio curto, enigmático e memorável, como o papel encontrado dentro de um biscoito da sorte.
        Use imagens, metáforas e observações inesperadas sobre escolhas, acaso, ambição, amizade, teimosia, sorte ou consequências.
        Varie bastante o assunto, a construção das frases e o tipo de metáfora. Evite fórmulas prontas e não repita sempre a mesma ideia.

        **PERSONALIZAÇÃO OPCIONAL**
        {identity_context}
        Se houver classe, lore ou tags, você pode usar um detalhe de forma sutil quando combinar naturalmente com o provérbio.
        Não force referências ao personagem em toda resposta e não invente acontecimentos ou fatos pessoais.
        O provérbio deve continuar parecendo uma mensagem de biscoito da sorte, não uma ficha de RPG.

        **DIREÇÃO CRIATIVA**
        - Não use templos, santuários, torii, monges, espíritos ou cenários religiosos como tema padrão.
        - Não mencione um local de origem para o biscoito.
        - Explore cenários e metáforas diferentes; não fique preso a uma estética específica.
        - Seja espirituoso, ambíguo ou levemente irônico quando combinar.

        **REGRAS DE FORMATO**
        1. Comece a resposta exatamente com "glorp".
        2. Depois de "glorp", escreva somente o provérbio, sem emojis.
        3. Não inclua comentário, explicação, assinatura, saudação ou observação adicional.
        4. Não use hífen com espaços nem travessão para separar um comentário.
        5. Máximo de 250 caracteres no total.
        6. Não gere números de sorte; eles serão adicionados pelo sistema.

        Resposta para @{author}:
        """

    def _generate_fortune_thread(self, channel: str, author: str, cookie_gain: int, lucky_numbers: str):
        """Gera a mensagem e monta a resposta final."""
        try:
            gain_text = None
            if self.bot.cookie_system and self.bot.cookie_system.add_cookies(author, cookie_gain, award_xp=True):
                gain_text = self._format_cookie_gain(cookie_gain)

            self.bot.training_logger.log_interaction(channel, author, "*cookie", None)
            prompt = self._build_prompt(author)

            response = self.bot.gemini_client.get_response(
                query=prompt,
                channel=channel,
                author=author,
                memory_mgr=self.bot.memory_mgr,
                skip_search=True,
                live_context=self.bot.get_live_context(channel),
            )

            if response:
                clean_response = self._clean_generated_text(response)
                if not clean_response:
                    clean_response = "A sorte favorece quem percebe a oportunidade antes que ela passe."

                final_msg = f"glorp {clean_response} | Números da sorte: [{lucky_numbers}]"
                if gain_text:
                    final_msg += f" | {gain_text}"

                self.bot.send_long_message(channel, final_msg)
            else:
                error_msg = f"glorp @{author}, a sorte não trouxe uma mensagem desta vez (erro na API)."
                if gain_text:
                    error_msg += f" | {gain_text}"
                self.bot.send_message(channel, error_msg)

        except Exception as e:
            logging.error("[FortuneCookie] Falha ao gerar sorte: %s", e)
            self.bot.send_message(channel, f"glorp @{author}, não foi possível abrir seu biscoito agora. Tente novamente.")
