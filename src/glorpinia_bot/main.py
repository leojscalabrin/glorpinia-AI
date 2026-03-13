import os
os.environ['GLORPINIA_ALLOW_NO_LANGCHAIN'] = '1'

import time
import logging
import signal
import sys
import re
import requests
import threading
from datetime import datetime
from collections import deque
import subprocess
import random
from google.cloud import speech

from .twitch_auth import TwitchAuth
from .gemini_client import GeminiClient
from .memory_manager import MemoryManager
from .emote_manager import EmoteManager
from .narrative.social_dynamics import SocialDynamicsEngine

from .features.comment import Comment
from .features.listen import Listen
from .features.training_logger import TrainingLogger
from .features.eight_ball import EightBall
from .features.fortune_cookie import FortuneCookie
from .features.cookie_system import CookieSystem
from .features.slots import Slots
from .features.analysis import AnalysisMode
from .features.tarot import TarotReader
from .features.rpg_roll import RPGRollFeature

log_level_name = os.getenv("GLORPINIA_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level_name, logging.INFO),
    format="%(asctime)s:%(levelname)s:%(name)s:%(message)s"
)

class TwitchIRC:
    TOPIC_MIN_OCCURRENCES = 3
    TOPIC_SCAN_WINDOW = 25
    IMPERIAL_TAX_PROBABILITY = 0.008
    IMPERIAL_TAX_COOLDOWN_SECONDS = 900

    def __init__(self):
        # Core Auth (sempre necessário)
        self.auth = TwitchAuth()  # Carrega env, tokens, profile, channels
        
        # Configurações de Estado
        self.chat_enabled = True  # Para respostas a menções
        
        self.IGNORED_NICKS = {
            "system", "usuario", "user", "usuário", "você", "eu", "everyone", "here", "chat",
            "pokemoncommunitygame", "streamelements", "nightbot", 
            "wizebot", "creatisbot", "own3d"
        }
        
        print("[INFO] Starting Glorpinia Bot in FULL MODE.")

        # Inicializa Componentes Pesados
        self.speech_client = None
        try:
            self.speech_client = speech.SpeechClient()
        except Exception as e:
            print(f"[ERROR] Falha ao inicializar Google Speech Client: {e}")

        self.gemini_client = GeminiClient(
            personality_profile=self.auth.personality_profile
        )
        self.memory_mgr = MemoryManager()
        self.emote_manager = EmoteManager()
        self.social_dynamics = SocialDynamicsEngine()
        
        self.live_status = {} # Dicionário para guardar { 'canal': True/False }
        
        # Define como True antes de iniciar a thread
        self.running = True 
        
        # Inicia a thread que vai ficar checando a API da Twitch em segundo plano
        self.monitor_thread = threading.Thread(target=self._monitor_live_status, daemon=True)
        self.monitor_thread.start()
        
        # Inicializa Features
        print("[INFO] Loading features...")
        self.comment_feature = Comment(self)
        self.listen_feature = Listen(self, self.speech_client)
        self.training_logger = TrainingLogger(self)
        self.cookie_system = CookieSystem(self)
        self.eight_ball_feature = EightBall(self)
        self.fortune_cookie_feature = FortuneCookie(self)
        self.slots_feature = Slots(self)
        self.gemini_client.set_cookie_system(self.cookie_system)
        self.analysis_feature = AnalysisMode(self)
        self.tarot_feature = TarotReader(self)
        self.rpg_feature = RPGRollFeature(self)

        # Cache e Utilitários
        self.processed_message_ids = deque(maxlen=500)
        self.recent_messages = {channel: deque(maxlen=100) for channel in self.auth.channels}
        self.last_bot_message_by_channel = {}
        
        # Cooldown timer para o trigger "oziell"
        self.last_oziell_time = 0
        self.last_imperial_tax_time_by_channel = {}

        # Lista de Admins
        admin_nicks_str = os.getenv("ADMIN_NICKS") 
        self.admin_nicks = [nick.strip().lower() for nick in admin_nicks_str.split(',')] if admin_nicks_str else []
        print(f"[AUTH] Admins carregados: {self.admin_nicks}")

        # Configuração do WebSocket e Shutdown
        self.ws = None
        
        # Validação inicial do Token
        self.auth.validate_and_refresh_token()
        
        signal.signal(signal.SIGINT, self.handle_exit)
        signal.signal(signal.SIGTERM, self.handle_exit)


    def handle_exit(self, signum, frame):
        """
        Handler para shutdown.
        Salva dados pendentes e fecha conexões antes de morrer.
        """
        print("\n[INFO] Sinal de shutdown recebido. Iniciando limpeza...")
        
        # Parar features que podem estar escrevendo em disco/DB
        if hasattr(self, 'cookie_system') and self.cookie_system:
            print("[SHUTDOWN] Salvando dados bancários (Cookies)...")
            if hasattr(self.cookie_system, 'stop_thread'):
                self.cookie_system.stop_thread()

        if hasattr(self, 'training_logger') and self.training_logger:
            # Garante que o último log de treino seja salvo
            pass 

        # Parar threads de loop
        if hasattr(self, 'comment_feature') and self.comment_feature:
            self.comment_feature.stop_thread()
            
        if hasattr(self, 'listen_feature') and self.listen_feature:
            self.listen_feature.stop_thread()
            
        print("[INFO] Fechando conexão com a Twitch...")
        self.running = False
        if self.ws:
            self.ws.close()
            
        print("[INFO] Encerrado com sucesso.")
        sys.exit(0)

    def send_message(self, channel, message):
        """Envia mensagem via WebSocket."""
        if self.ws and self.ws.sock and self.ws.sock.connected:
            full_msg = f"PRIVMSG #{channel} :{message}\r\n"
            self.ws.send(full_msg)
            print(f"[BOT] {channel}: {message}")
            self._register_recent_message(channel, self.auth.bot_nick, message)
        else:
            print(f"[ERROR] WebSocket nao conectado. Nao foi possivel enviar: {message}")

    def _register_recent_message(self, channel, author, content):
        if channel not in self.recent_messages:
            self.recent_messages[channel] = deque(maxlen=100)

        self.recent_messages[channel].append({
            "author": author,
            "content": content,
            "timestamp": time.time()
        })
    
    def _send_message_part(self, channel, part, delay):
        """[HELPER] Espera (em um thread) e envia uma parte da mensagem."""
        try:
            time.sleep(delay)
            # Verifica conexão antes de enviar
            if self.ws and self.ws.sock and self.ws.sock.connected:
                full_msg = f"PRIVMSG #{channel} :{part}\r\n"
                self.ws.send(full_msg)
                print(f"[BOT-PART] {channel}: {part}")
                self._register_recent_message(channel, self.auth.bot_nick, part)
            else:
                print(f"[ERROR] WebSocket desconectado ao tentar enviar parte: {part}")
        except Exception as e:
            print(f"[ERROR] Falha ao enviar parte da mensagem no thread: {e}")

    def send_long_message(self, channel, message, max_length=350, split_delay_sec=2):
        """
        Envia uma mensagem, dividindo-a com segurança para não estourar 350 bytes
        """
        # Limpeza extra de espaços
        message = message.strip()
        
        # Se couber com segurança, envia direto
        if len(message) <= max_length:
            self.send_message(channel, message)
            return

        print(f"[INFO] Mensagem longa ({len(message)} chars). Dividindo...")
        
        words = message.split()
        parts = []
        current_part = ""

        # Monta as partes respeitando o limite
        for word in words:
            # +1 é o espaço
            if len(current_part) + len(word) + 1 > max_length:
                if current_part: 
                    parts.append(current_part.strip())
                current_part = word + " "
            else:
                current_part += word + " "
        
        if current_part:
            parts.append(current_part.strip())

        # Envia as partes com delay
        current_delay = 0
        total_parts = len(parts)
        
        for i, part in enumerate(parts):
            # Adiciona indicador (1/2) apenas se tiver mais de uma parte
            if total_parts > 1:
                part_with_indicator = f"({i+1}/{total_parts}) {part}"
            else:
                part_with_indicator = part
            
            # Última checagem de segurança no tamanho da parte
            if len(part_with_indicator) > max_length + 20: # Margem pequena para o indicador
                part_with_indicator = part_with_indicator[:max_length] + "..."

            # A primeira parte vai rápido, as outras esperam
            delay = 0 if i == 0 else current_delay
            
            t = threading.Thread(target=self._send_message_part, 
                                 args=(channel, part_with_indicator, delay))
            t.daemon = True
            t.start()
            
            # Incrementa o delay apenas para as próximas
            if i > 0:
                current_delay += split_delay_sec
            else:
                current_delay = split_delay_sec

    def prepare_final_bot_message(self, channel, response_text, mood=None, source="chat", context_text=None):
        """Normaliza saída, evita repetição e escolhe emote conforme contexto + mood."""
        cleaned_text = self.emote_manager.remove_known_emotes(response_text or "")
        cleaned_text = self.emote_manager.strip_trailing_emote(cleaned_text)
        unique_text = self.emote_manager.ensure_unique_phrase(channel, cleaned_text)
        selected_emote = self.emote_manager.choose_emote(channel, unique_text, mood=mood, context_text=context_text)
        final_text = f"{unique_text} {selected_emote}".strip()

        last = self.last_bot_message_by_channel.get(channel)
        if last and last == final_text:
            unique_text = self.emote_manager.ensure_unique_phrase(channel, f"{unique_text} ")
            selected_emote = self.emote_manager.choose_emote(channel, unique_text, mood=mood, context_text=context_text)
            final_text = f"{unique_text} {selected_emote}".strip()

        self.last_bot_message_by_channel[channel] = final_text
        emote_debug = self.emote_manager.get_debug_state(channel)
        logging.debug(
            "[Main] emote_debug source=%s channel=%s last_channel=%s last_global=%s selected=%s",
            source,
            channel,
            emote_debug.get("last_channel_emote"),
            emote_debug.get("last_global_emote"),
            emote_debug.get("last_selected_channel"),
        )
        logging.debug(
            "[Main] final_message source=%s channel=%s mood=%s emotion=%s text=%s",
            source,
            channel,
            mood,
            emote_debug.get("last_resolved_emotion"),
            final_text,
        )
        return final_text

    def _format_admin_debug_message(self, channel):
        social_debug = self.social_dynamics.get_debug_snapshot()
        emote_debug = self.emote_manager.get_debug_state(channel)

        drama_state = social_debug.get("drama_state", {})
        rivals = drama_state.get("rivalries") or []
        users_seen = social_debug.get("users_seen", [])
        random_params = social_debug.get("random_roll_parameters", {})

        def _fmt(name, value):
            return f"{name}: {value if value else '-'}"

        social_summary = (
            f"Mood: {social_debug.get('mood', 'neutral')}({social_debug.get('mood_duration', 0)}) | "
            f"{_fmt('Fav', drama_state.get('favorite_of_the_day'))} | "
            f"{_fmt('Enemy', drama_state.get('enemy_of_the_day'))} | "
            f"{_fmt('Suspect', drama_state.get('suspect'))} | "
            f"Rivais: {', '.join(rivals) if rivals else '-'} | "
            f"Users: {len(users_seen)}"
        )

        emote_summary = (
            f"Emote último(canal/global): {emote_debug.get('last_channel_emote') or '-'} / "
            f"{emote_debug.get('last_global_emote') or '-'} | "
            f"Emote escolhido(msg): {emote_debug.get('last_selected_channel') or '-'}"
        )

        params_summary = (
            "Rolls drama => "
            f"fav:{random_params.get('favorite_probability', 0):.3f}, "
            f"enemy:{random_params.get('enemy_probability', 0):.3f}, "
            f"suspect:{random_params.get('suspect_probability', 0):.3f}, "
            f"loop:{random_params.get('memory_loop_probability', 0):.3f}"
        )

        return social_summary, emote_summary, params_summary

    def _extract_topic_candidate(self, content: str):
        text = (content or "").lower().strip()
        if not text:
            return None

        text = re.sub(r"https?://\S+", " ", text)
        text = re.sub(r"[^\w\sáàãâéêíóôõúç]", " ", text)

        stopwords = {
            "de", "da", "do", "das", "dos", "em", "na", "no", "pra", "para", "que", "com",
            "uma", "um", "as", "os", "eu", "tu", "ele", "ela", "isso", "isto", "aqui", "ali",
            "tipo", "mano", "bot", "glorpinia", "glorp", "kkk", "kkkk", "k", "rs", "rss", "haha",
            "não", "sim", "mais", "muito", "pouco", "como", "porque", "por", "se", "me", "te",
        }

        words = [w for w in text.split() if len(w) >= 4 and w not in stopwords and not w.startswith("@")] 
        if not words:
            return None
        return " ".join(words[:4])

    def _maybe_register_recurring_memory_loop(self, channel: str, author: str, content: str):
        if channel not in self.recent_messages:
            return

        topic_candidate = self._extract_topic_candidate(content)
        if not topic_candidate:
            return

        recent = list(self.recent_messages[channel])[-self.TOPIC_SCAN_WINDOW :]
        occurrences = 0
        authors = set()
        for msg in recent:
            msg_topic = self._extract_topic_candidate(msg.get("content", ""))
            if msg_topic == topic_candidate:
                occurrences += 1
                author_name = (msg.get("author") or "").lower()
                if author_name:
                    authors.add(author_name)

        if occurrences < self.TOPIC_MIN_OCCURRENCES:
            return

        users = sorted(authors | {author.lower()})
        self.social_dynamics.add_memory_loop(topic=topic_candidate, users=users, weight=0.55, loop_type="recurring_topic")
        logging.debug(
            "[Main] recurring_topic loop_created channel=%s topic=%s occurrences=%s users=%s",
            channel,
            topic_candidate,
            occurrences,
            users,
        )


    def _roll_imperial_tax_trigger(self, channel: str):
        """
        Trigger randômico de imposto imperial baseado em TODO fluxo de mensagens do chat.
        Não depende de menção direta ao bot.
        """
        if not self.cookie_system or not self.gemini_client:
            return

        now = time.time()
        last_time = self.last_imperial_tax_time_by_channel.get(channel, 0)
        if (now - last_time) < self.IMPERIAL_TAX_COOLDOWN_SECONDS:
            return

        if self.live_status.get(channel, False):
            return

        if random.random() > self.IMPERIAL_TAX_PROBABILITY:
            return

        top_debtors = self.cookie_system.get_debt_leaderboard(1)
        if not top_debtors:
            return

        target_user, debt_value = top_debtors[0]
        target_user = target_user.lower()
        if target_user in {self.auth.bot_nick.lower(), "system", "user", "usuario"}:
            return

        tax_amount = min(20, max(5, abs(int(debt_value)) // 5 or 5))
        self.cookie_system.remove_cookies(target_user, tax_amount)

        try:
            injection_context = self.social_dynamics.get_injection_payload()
            prompt = (
                f"A corte imperial executou um imposto surpresa em @{target_user} de {tax_amount} cookies "
                f"(saldo devedor atual: {debt_value}). Faça um anúncio curto, dramático e divertido em 1 frase."
            )
            tax_message = self.gemini_client.get_response(
                query=prompt,
                channel=channel,
                author="system",
                memory_mgr=self.memory_mgr,
                skip_search=True,
                injection_context=injection_context,
                allow_cookie_actions=False,
            )
            clean = (tax_message or "").replace("@system, ", "").strip()
            if clean:
                self.send_message(channel, clean)
        except Exception as exc:
            logging.error("[Main] Falha no trigger de imposto imperial: %s", exc)
            self.send_message(channel, f"Imposto imperial aplicado em @{target_user}: -{tax_amount}🍪")

        self.last_imperial_tax_time_by_channel[channel] = now

    def on_message(self, ws, message):
        """Handler de mensagens IRC (usa o cliente LLM)."""
        if message.startswith("PING"):
            ws.send("PONG :tmi.twitch.tv\r\n")
            return

        if " JOIN #" in message:
            try:
                channel_joined = message.split("#")[1].strip()
                print(f"[DEBUG] Sucesso! Conectado ao chat do canal: #{channel_joined}")
            except:
                pass
            return
            
        # Processar mensagens de chat (PRIVMSG)
        match = re.search(r":(\w+)!\w+@\w+\.tmi\.twitch\.tv PRIVMSG #(\w+) :(.*)", message)
        if match:
            author, channel, content = match.groups()
            content = content.strip()
            content_lower = content.lower()
            
            author_lower = author.lower()
            
            # Ignora mensagens do próprio bot
            if author_lower == self.auth.bot_nick.lower() or author_lower in self.IGNORED_NICKS:
                return

            if content_lower.startswith("voltei") or content_lower.startswith("cheguei"):
                self.send_message(channel, "Então to indo nessa pessoal peepoHey")
                return
            
            self.social_dynamics.observe_message(author, content, bot_nick=self.auth.bot_nick)

            # Salvar no Histórico Recente (Memória de Curto Prazo)
            self._register_recent_message(channel, author, content)
            logging.debug(
                "[Main] recent_message_history channel=%s size=%s last_author=%s",
                channel,
                len(self.recent_messages[channel]),
                author,
            )
            self._maybe_register_recurring_memory_loop(channel, author, content)
            self._roll_imperial_tax_trigger(channel)

            # PROCESSA COMANDOS E TRIGGERS

            if content_lower == 'glorp':
                self.send_message(channel, 'glorp')
                return

            if content.startswith("*"):
                parts = content.split()
                command_raw = parts[0][1:].lower()

                if command_raw == "8ball":
                    self.social_dynamics.add_memory_loop(topic="previsões duvidosas do 8ball", users=[author_lower], weight=0.45)
                    question = " ".join(parts[1:])
                    if not question:
                        self.send_message(channel, f"@{author}, faça uma pergunta! glorp")
                        return
                    self.eight_ball_feature.get_8ball_response(question, channel, author)
                    return
                
                if command_raw == "cookie":
                    if self.fortune_cookie_feature:
                        self.fortune_cookie_feature.get_fortune(channel, author)
                    return

                if command_raw == "slots":
                    if self.live_status.get(channel, False):
                        self.send_message(channel, f"@{author} O KASSINÃO está fechado durante a live Stare")
                        return

                    if self.slots_feature:
                        bet = 10
                        if len(parts) > 1:
                            if parts[1].lower() == "all":
                                bet = "all"
                            else:
                                try:
                                    bet = int(parts[1])
                                except ValueError:
                                    pass
                        
                        result = self.slots_feature.play(channel, author, bet)
                        self.send_message(channel, result)
                    return

                if command_raw == "balance":
                    if self.cookie_system:
                        target = author.lower()
                        if len(parts) > 1:
                            target = parts[1].lower().replace("@", "")
                        
                        if target == self.auth.bot_nick.lower():
                            return

                        count = self.cookie_system.get_cookies(target)
                        if target == author.lower():
                            self.send_message(channel, f"@{author}, você tem {count}🍪 glorp")
                        else:
                            self.send_message(channel, f"@{author}, {target} tem {count}🍪  glorp")
                    return

                if command_raw == "empire":
                    if self.cookie_system:
                        bot_nick = self.auth.bot_nick.lower()
                        count = self.cookie_system.get_cookies(bot_nick)
                        
                        empire_query = f"Seu império de cookies já acumulou {count} cookies. Faça um comentário curto (uma frase), triunfante, arrogante e divertido sobre como sua dominação galática está sendo financiada por esses 'tributos' dos humanos."
                        
                        try:
                            comment = self.gemini_client.get_response(
                                empire_query, channel, "system", self.memory_mgr
                            )
                            if comment:
                                self.send_message(channel, f"O império já arrecadou {count}🍪 EZ Clap {comment}")
                            else:
                                self.send_message(channel, f"O império já arrecadou {count}🍪 EZ Clap")
                        except Exception:
                            self.send_message(channel, f"O império já arrecadou {count}🍪 EZ Clap")
                    return

                if command_raw == "leaderboard":
                    if self.cookie_system:
                        top = self.cookie_system.get_leaderboard(5)
                        if not top:
                            self.send_message(channel, "glorp Sem barões dos cookies ainda! Sadge")
                        else:
                            msg = "Barões dos Cookies: " + " , ".join([f"#{i+1} {n} [{c} 🍪]" for i, (n, c) in enumerate(top)])
                            self.send_message(channel, f"glorp {msg}")
                    return
                
                if command_raw == "commands":
                    self.send_message(channel, "glorp Comandos: *analysis, *8ball, *cookie, *balance, *empire, *leaderboard, *debt, *slots, *fortune, *roll, *check, *scan, *chat, *listen, *comment (Use *help [comando] para detalhes)")
                    return
                
                if command_raw == "help":
                    cmd_target = parts[1].lower() if len(parts) > 1 else ""
                    
                    if not cmd_target:
                        self.send_message(channel, "glorp Use *help [comando]. Ex: *help slots")
                        return
                    
                    help_msg = {
                        "check": "glorp checa status das features.",
                        "slots": "glorp aposte cookies! *slots [valor] (min 10).",
                        "8ball": "glorp Pergunte ao oráculo! *8ball [pergunta].",
                        "cookie": "glorp Pegue seu biscoito da sorte diário.",
                        "balance": "glorp Veja seu saldo ou de outro. *balance @nick.",
                        "empire": "glorp Veja o tamanho do cofre da Imperatriz Glorpinia.",
                        "leaderboard": "glorp Top 5 magnatas dos cookies.",
                        "commands": "glorp Lista todos os comandos.",
                        "chat": "(Admin) Toggle chat. Ex: *chat on", 
                        "listen": "(Admin) Toggle listen. Ex: *listen on", 
                        "comment": "(Admin) Toggle comment. Ex: *comment on", 
                        "scan": "(Admin) Scan manual.",
                        "debug": "(Admin) Mostra mood atual, drama state do dia e debug de emotes.",
                        "addcookie": "(Admin) Add cookies. Ex: *addcookie nick 100", 
                        "removecookie": "(Admin) Remove cookies. Ex: *removecookie nick 100",
                        "analysis": "Análise de um assunto, dúvidas ou resumo do chat. Ex: *analysis [pergunta específica]",
                        "help": "Você deve estar precisando mesmo nise",
                        "fortune": "Tire uma leitura do seu arcano",
                        "roll": "Rolar um D20 para RPG com narração temática. Ex: *roll [ação desejada]",
                        "debt": "Veja os maiores devedores do império (quem deve mais cookies)."
                    }
                    self.send_message(channel, help_msg.get(cmd_target, "glorp Comando desconhecido."))
                    return
                
                if command_raw == "analysis" or command_raw == "analise" or command_raw == "análise":
                    specific_query = " ".join(parts[1:])

                    self.analysis_feature.trigger_analysis(channel, author, specific_query)
                    return
                
                if command_raw == "fortune" or command_raw == "tarot":
                    self.social_dynamics.add_memory_loop(topic="tarot e previsões", users=[author_lower], weight=0.45)
                    target = None
                    if len(parts) > 1:
                        target = parts[1]
                    
                    self.tarot_feature.read_fate(channel, author, target)
                    return
                
                if command_raw == "roll" or command_raw == "d20":
                    self.social_dynamics.add_memory_loop(topic="dados do caos", users=[author_lower], weight=0.45)
                    query = " ".join(parts[1:]) if len(parts) > 1 else ""

                    self.rpg_feature.trigger_roll(channel, author, query)
                    return
                
                # COMANDOS DE ADMIN (Verificação)
                admin_cmds = ["chat", "listen", "comment", "scan", "addcookie", "removecookie", "check", "debug"]
                
                if command_raw in admin_cmds:
                    if author.lower() in self.admin_nicks:
                        self.handle_admin_command(content, channel)
                    else:
                        self.send_message(channel, f"@{author}, comando apenas para os chegados arnoldHalt")
                    return

                if command_raw == "debt" or command_raw == "divida":
                    if self.cookie_system:
                        top_debtors = self.cookie_system.get_debt_leaderboard(5)
                        if not top_debtors:
                            self.send_message(channel, "baseg Ninguém deve ao império! Todos estão em dia.")
                        else:
                            msg = "Esses são os maiores devedores galáticos: " + " | ".join([f"#{i+1} {n} [{c} 🍪]" for i, (n, c) in enumerate(top_debtors)])
                            self.send_message(channel, f"xdd {msg}")
                    return
                
                # Se chegou aqui com *, é comando desconhecido
                self.send_message(channel, "glorp Comando desconhecido. Use *commands")
                return
            
            # MENÇÕES DIRETAS À IA
            if self.chat_enabled and self.auth.bot_nick.lower() in content_lower:
                print(f"[DEBUG] Bot mencionado por {author}. Gerando resposta...")
                
                if self.cookie_system:
                    self.cookie_system.handle_interaction(author.lower())

                try:
                    # Convertendo Deque para List para a IA poder ler
                    recent_history_list = list(self.recent_messages.get(channel, []))
                    
                    enriched_content = content
                    if self.cookie_system:
                        system_notes = []
                        # Pega o saldo de quem falou
                        author_bal = self.cookie_system.get_cookies(author.lower())
                        system_notes.append(f"{author}: {author_bal}🍪")
                        
                        # Tenta pegar o saldo de alguém que ele mencionou na mensagem
                        for w in content_lower.split():
                            if w.startswith("@"):
                                target_nick = w.replace("@", "").strip()
                                if target_nick and target_nick != self.auth.bot_nick.lower():
                                    target_bal = self.cookie_system.get_cookies(target_nick)
                                    system_notes.append(f"{target_nick}: {target_bal}🍪")
                        
                        if system_notes:
                            unique_notes = list(set(system_notes))
                            enriched_content += f"\n\n[SISTEMA: Saldos atuais -> {' | '.join(unique_notes)}. Se o saldo for negativo, a pessoa é uma devedora/caloteira do Império.]"
                    
                    if self.gemini_client and self.memory_mgr:
                        injection_context = self.social_dynamics.get_injection_payload()
                        response_text = self.gemini_client.get_response(
                            query=enriched_content,
                            channel=channel, 
                            author=author, 
                            memory_mgr=self.memory_mgr,
                            recent_history=recent_history_list,
                            injection_context=injection_context,
                            allow_cookie_actions=True,
                        )
                        
                        if response_text:
                            current_mood = (injection_context or {}).get("mood")
                            final_text = self.prepare_final_bot_message(
                                channel=channel,
                                response_text=response_text,
                                mood=current_mood,
                                source="mention",
                                context_text=content,
                            )
                            self.send_long_message(channel, final_text)
                            
                            if self.training_logger:
                                self.training_logger.log_interaction(
                                    channel, 
                                    author, 
                                    content,
                                    final_text
                                )

                except Exception as e:
                    print(f"[ERROR] Falha ao gerar resposta: {e}")
                
                return

            # Triggers Passivos
            if "!oziell" in content_lower:
                now = time.time()
                if (now - self.last_oziell_time) > 1800:
                    self.last_oziell_time = now
                    self.send_message(channel, "Olá @oziell ! Tudo bem @oziell ? Tchau @oziell !")
                return 
            
            if "thomezord fiddy" in content_lower:
                self.send_message(channel, "thomezord Fiddy")
                return
        
            # Duplicatas (Log Anti-Spam do console)
            unique_id = f"{author}-{channel}-{content}"
            msg_hash = hash(unique_id)
            if msg_hash in self.processed_message_ids:
                return
            self.processed_message_ids.append(msg_hash)

            # Comment Trigger
            if self.comment_feature:
                self.comment_feature.roll_for_comment(channel, author)
            
    def handle_admin_command(self, command, channel):
        """Processa comandos de admin."""
        parts = command.split()
        command_name = parts[0][1:].lower()
        
        # Comandos sem argumento (*check) -> len 1
        if len(parts) == 1:
            if command_name == "check":
                c_st = "ON" if self.chat_enabled else "OFF"
                l_st = self.listen_feature.get_status() if self.listen_feature else "?"
                cm_st = self.comment_feature.get_status() if self.comment_feature else "?"
                self.send_message(channel, f"Status: peepoChat Chat {c_st} | glorp 📡 Listen {l_st} | peepoTalk Comment {cm_st}")
                return
            elif command_name == "commands":
                self.send_message(channel, "glorp Comandos: 8ball, cookie, balance, empire, leaderboard, slots, help, fortune, analysis, roll, (ADMIN): chat/listen/comment [on/off], addcookie/removecookie [nick] [valor], check, scan, debug")
                return
            elif command_name == "scan" and self.listen_feature:
                self.listen_feature.trigger_manual_scan(channel)
                return
            elif command_name == "debug":
                social_summary, emote_summary, params_summary = self._format_admin_debug_message(channel)
                self.send_long_message(channel, f"[DEBUG] {social_summary}")
                self.send_long_message(channel, f"[DEBUG] {emote_summary}")
                self.send_long_message(channel, f"[DEBUG] {params_summary}")
                return
        
        # Comandos com 3 argumentos (*addcookie nick 10) -> len 3
        if len(parts) == 3 and self.cookie_system:
            target = parts[1].lower().replace("@", "")
            try:
                val = int(parts[2])
                if val <= 0: raise ValueError
                if command_name == "addcookie":
                    self.cookie_system.add_cookies(target, val)
                    self.send_message(channel, f"glorp +{val} 🍪  para {target}.")
                elif command_name == "removecookie":
                    self.cookie_system.remove_cookies(target, val)
                    self.send_message(channel, f"glorp -{val} 🍪  de {target}.")
                return
            except ValueError:
                self.send_message(channel, "glorp Valor inválido.")
                return
        
        # Comandos com 2 argumentos (*chat on) -> len 2
        if len(parts) == 2:
            state = (parts[1].lower() == "on")
            
            if command_name == "chat":
                self.chat_enabled = state
                self.send_message(channel, f"peepoChat Chat {'ATIVADO' if state else 'DESATIVADO'}.")
                return
            elif command_name == "listen" and self.listen_feature:
                self.listen_feature.set_enabled(state)
                self.send_message(channel, f"glorp 📡 Listen {'ATIVADO' if state else 'DESATIVADO'}.")
                return
            elif command_name == "comment" and self.comment_feature:
                self.comment_feature.set_enabled(state)
                self.send_message(channel, f"peepoTalk Comment {'ATIVADO' if state else 'DESATIVADO'}.")
                return

        self.send_message(channel, "Comando inválido. Use *commands")


    def run(self):
        """Inicia a conexao WebSocket e o loop de mensagens."""
        import websocket

        self.running = True
        while self.running:
            try:
                print("[INFO] Validando token antes de conectar...")
                self.auth.validate_and_refresh_token()
                
                self.ws = websocket.WebSocketApp(
                    "wss://irc-ws.chat.twitch.tv:443",
                    on_message=self.on_message,
                    on_error=self.on_error,
                    on_close=self.on_close,
                    on_open=self.on_open
                )
                self.ws.run_forever()
            except Exception as e:
                print(f"[ERROR] WebSocket encontrou um erro: {e}")
                print("[INFO] Tentando reconectar em 10 segundos...")
                time.sleep(10)

    def on_open(self, ws):
        """Handler para quando a conexao WebSocket é aberta."""
        token_for_send = self.auth.access_token
        
        ws.send("CAP REQ :twitch.tv/membership twitch.tv/tags\r\n")
        
        ws.send(f"PASS oauth:{token_for_send}\r\n")
        ws.send(f"NICK {self.auth.bot_nick}\r\n")
        print(f"[AUTH] Autenticando como {self.auth.bot_nick} com token...")
        
        for channel in self.auth.channels:
            ws.send(f"JOIN #{channel}" + "\r\n")
            
            print(f"[JOIN] Tentando juntar ao canal: #{channel}")

    def on_error(self, ws, error):
        """Handler para erros do WebSocket."""
        print(f"[ERROR] WebSocket error: {error}")

    def on_close(self, ws, close_status_code, close_msg):
        """Handler para quando a conexao WebSocket é fechada."""
        print(f"[INFO] Conexao WebSocket fechada. Codigo: {close_status_code}, Msg: {close_msg}")

    def _monitor_live_status(self):
        """
        Thread secundário que verifica a cada 60s se os canais estão online.
        Renovação automática de Token em caso de erro 401.
        """
        print("[Monitor] Iniciando monitoramento de status da stream...")
        
        while self.running:
            for channel in self.auth.channels:
                url = f"https://api.twitch.tv/helix/streams?user_login={channel}"
                headers = {
                    "Client-ID": self.auth.client_id,
                    "Authorization": f"Bearer {self.auth.access_token}"
                }
                
                try:
                    response = requests.get(url, headers=headers, timeout=10)
                    
                    if response.status_code == 200:
                        data = response.json()
                        is_live = len(data.get("data", [])) > 0
                        
                        was_live = self.live_status.get(channel, False)
                        
                        # Atualiza estado
                        self.live_status[channel] = is_live
                        
                        # Detecta transições
                        if is_live and not was_live:
                            print(f"[Monitor] {channel} entrou AO VIVO!")
                            self._trigger_welcome_message(channel)
                        elif not is_live and was_live:
                            print(f"[Monitor] {channel} ficou OFFLINE!")
                            self._trigger_goodbye_message(channel)

                    # Tratamento de Token Expirado
                    elif response.status_code == 401:
                        print("[Monitor] Token expirado (401). Tentando renovação automática...")
                        
                        # Faz o refresh e atualiza o self.auth.access_token
                        if self.auth.validate_and_refresh_token():
                            print("[Monitor] Token renovado com sucesso! Reiniciando WebSocket...")
                            
                            # Força a desconexão do WebSocket. 
                            if self.ws:
                                self.ws.close()
                                
                            # Espera um pouco para garantir que a reconexão ocorra
                            time.sleep(5)
                        else:
                            print("[Monitor] Falha crítica ao renovar token. Tentando novamente em 60s.")

                    else:
                        print(f"[Monitor] Erro API Twitch: {response.status_code}")
                        
                except Exception as e:
                    print(f"[Monitor] Erro de conexão: {e}")
            
            time.sleep(60)
            
    def _trigger_welcome_message(self, channel):
        """
        Gera e envia uma mensagem de 'Boas Vindas' usando a IA.
        """
        try:
            prompt = (
                f"O streamer @{channel} acabou de iniciar a live! "
                "Como Glorpinia, mande uma mensagem curta, empolgada e fofa desejando uma ótima stream. "
                "Diga que estava esperando ele(a) chegar. Use emotes."
            )

            if self.gemini_client:
                response = self.gemini_client.get_response(prompt, channel, "system")
                
                # Limpeza: remove a menção ao @system que o bot adiciona automaticamente
                welcome_msg = response.replace("@system, ", "").strip()
                
                self.send_message(channel, welcome_msg)
            else:
                self.send_message(channel, f"LETSGO A LIVE COMEÇOU! Boa stream @{channel}! glorp")

        except Exception as e:
            print(f"[ERROR] Falha ao gerar welcome message: {e}")
            self.send_message(channel, f"LETSGO A LIVE COMEÇOU! Boa stream @{channel}!")
    
    def _trigger_goodbye_message(self, channel):
        """
        Gera e envia uma mensagem de despedida quando a live cai.
        """
        try:
            prompt = (
                f"O streamer @{channel} acabou de encerrar a live! "
                "Como Glorpinia, mande uma mensagem de despedida para o chat. "
                "Diga algo como 'finalmente paz', ou que vai voltar a consertar a nave/dormir. "
                "Seja fofa mas aliviada. Use emotes de sono ou despedida."
            )

            if self.gemini_client:
                response = self.gemini_client.get_response(prompt, channel, "system")
                
                goodbye_msg = response.replace("@system, ", "").strip()
                
                self.send_message(channel, goodbye_msg)
            else:
                self.send_message(channel, f"A live acabou! Até a próxima, humanos! peepoLeave")

        except Exception as e:
            print(f"[ERROR] Falha ao gerar goodbye message: {e}")
            self.send_message(channel, f"Fim da transmissão! A mimir Bedge")

if __name__ == "__main__":
    bot = TwitchIRC()
    bot.run()
