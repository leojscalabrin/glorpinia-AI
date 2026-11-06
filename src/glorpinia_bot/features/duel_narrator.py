"""Narrative-only duel resolution. All game mechanics remain in the command handler."""
import logging
import re
import threading

from ..narrative.rpg_context import format_group_identities


class DuelNarrator:
    MAX_NARRATIVE_CHARS = 420

    def __init__(self, bot):
        self.bot = bot

    def narrate_async(self, channel, challenger, opponent, winner, loser, bet_amount):
        """Generate a short combat scene after the deterministic duel has been settled."""
        worker = threading.Thread(
            target=self._generate_and_send,
            args=(channel, challenger, opponent, winner, loser, bet_amount),
            daemon=True,
        )
        worker.start()

    @staticmethod
    def _clean(text):
        clean = re.sub(r"\s+", " ", (text or "").replace("Duel:", "").strip())
        clean = re.sub(r"^glorp\s*", "", clean, flags=re.IGNORECASE)
        return clean.strip()

    def _generate_and_send(self, channel, challenger, opponent, winner, loser, bet_amount):
        try:
            identities = format_group_identities(self.bot, [challenger, opponent])
            prompt = f"""
[MODO: NARRADOR DE DUELOS DO RPG GLORPINIA]

PARTICIPANTES:
{identities}

RESULTADO JÁ DEFINIDO PELO SISTEMA:
- Desafiante: @{challenger}
- Oponente: @{opponent}
- Vencedor: @{winner}
- Derrotado: @{loser}
- Aposta transferida: {bet_amount} cookies

TAREFA:
Escreva uma cena curta que conte como o duelo aconteceu e como @{winner} venceu @{loser}.
Use as classes, especialidades, lore e tags dos dois personagens para dar identidade aos golpes, estratégias e reações.
Se um participante não tiver classe ou lore, descreva-o sem inventar uma classe ou passado.
A luta deve ter começo, uma virada ou movimento marcante e um desfecho coerente com o vencedor informado.
A personalidade e os recursos narrativos dos personagens podem ser criativos, mas não invente habilidades oficiais ou altere o resultado.
Não transforme tags em poderes automaticamente; use-as como traços ou referências quando combinarem.
Não inclua resultados de dados, novas apostas, recompensas, ferimentos permanentes ou consequências mecânicas.
Não use violência gráfica. Mantenha humor e clima de fantasia/caos de chat.
Responda em português, em 2 a 4 frases, com no máximo {self.MAX_NARRATIVE_CHARS} caracteres.
Não use markdown, emojis, listas ou texto antes/depois da cena.
"""
            response = self.bot.gemini_client.get_response(
                query=prompt,
                channel=channel,
                author="system",
                memory_mgr=None,
                skip_search=True,
                live_context=self.bot.get_live_context(channel),
            )
            narrative = self._clean(response)
            if not narrative:
                narrative = f"@{winner} encontrou a abertura certa, superou a defesa de @{loser} e encerrou o duelo com uma jogada decisiva."

            if len(narrative) > self.MAX_NARRATIVE_CHARS:
                narrative = narrative[:self.MAX_NARRATIVE_CHARS].rsplit(" ", 1)[0].rstrip(" ,;:") + "..."
            self.bot.send_long_message(
                channel,
                f"glorp {narrative} | {winner} venceu: +{bet_amount} cookies para @{winner}; -{bet_amount} cookies de @{loser}.",
            )
        except Exception as exc:
            logging.exception("[Duel] Falha ao gerar narrativa: %s", exc)
            self.bot.send_message(
                channel,
                f"glorp @{winner} venceu o duelo contra @{loser}! (+{bet_amount} cookies para @{winner}; -{bet_amount} cookies de @{loser}).",
            )
