import sys
import os
import logging

sys.path.insert(0, "src")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

from glorpinia_bot.twitch_auth import TwitchAuth
from glorpinia_bot.emote_manager import EmoteManager
from glorpinia_bot.seventv_channel_sync import SevenTVChannelSync


class FakeBot:
    """Só o suficiente pra SevenTVChannelSync funcionar (auth + emote_manager)."""
    def __init__(self):
        self.auth = TwitchAuth()
        self.auth.validate_and_refresh_token()
        self.emote_manager = EmoteManager()


def main():
    channel = sys.argv[1] if len(sys.argv) > 1 else None

    bot = FakeBot()
    if not channel:
        if not bot.auth.channels:
            print("Nenhum canal em TWITCH_CHANNELS e nenhum canal passado por argumento.")
            return
        channel = bot.auth.channels[0]

    sync = SevenTVChannelSync(bot)

    print(f"\n=== Sincronizando set GLOBAL ===")
    sync._sync_global(force=True)

    print(f"\n=== Sincronizando canal '{channel}' ===")
    sync._sync_channel(channel, force=True)

    print("\n=== Resultado: mapa GLOBAL classificado ===")
    for emotion, names in sorted(bot.emote_manager.global_emote_map.items()):
        print(f"  {emotion:15s} ({len(names)}): {names[:10]}{' ...' if len(names) > 10 else ''}")

    print(f"\n=== Resultado: mapa do canal '{channel}' ===")
    channel_map = bot.emote_manager.channel_emote_map.get(channel.lower(), {})
    if not channel_map:
        print("  (vazio -- canal sem emote-set no 7TV, ou erro na sincronização, veja o log acima)")
    for emotion, names in sorted(channel_map.items()):
        print(f"  {emotion:15s} ({len(names)}): {names[:10]}{' ...' if len(names) > 10 else ''}")

    neutral_count = len(channel_map.get("neutral", []))
    total_count = sum(len(v) for v in channel_map.values())
    if total_count:
        print(f"\nTaxa de classificação: {total_count - neutral_count}/{total_count} "
              f"({100 * (total_count - neutral_count) / total_count:.0f}%) emotes caíram fora de 'neutral'.")


if __name__ == "__main__":
    main()