import os
os.environ['GLORPINIA_ALLOW_NO_LANGCHAIN'] = '1'

import time
import logging
import signal
import sys
import re
import threading
from datetime import datetime
from collections import deque
import subprocess
from google.cloud import speech

from .twitch_auth import TwitchAuth
from .gemini_client import GeminiClient
from .memory_manager import MemoryManager

from .features.comment import Comment
from .features.listen import Listen
from .features.training_logger import TrainingLogger
from .features.eight_ball import EightBall
from .features.fortune_cookie import FortuneCookie
from .features.cookie_system import CookieSystem
from .features.slots import Slots

logging.basicConfig(level=logging.INFO, format="%(asctime)s:%(levelname)s:%(name)s:%(message)s")

class TwitchIRC:
    def __init__(self):
        # Core Auth (sempre necessário)
        self.auth = TwitchAuth()  # Carrega env, tokens, profile, channels
        
        # Configurações de Estado
        self.chat_enabled = True  # Para respostas a menções
        
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
        
        # Inicializa Features
        print("[INFO] Loading features...")
        self.comment_feature = Comment(self)
        self.listen_feature = Listen(self, self.speech_client)
        self.training_logger = TrainingLogger(self)
        self.cookie_system = CookieSystem(self)
        self.eight_ball_feature = EightBall(self)
        self.fortune_cookie_feature = FortuneCookie(self)
        self.slots_feature = Slots(self)

        # Cache e Utilitários
        self.processed_message_ids = deque(maxlen=500)
        self.recent_messages = {channel: deque(maxlen=100) for channel in self.auth.channels}
        
        # Cooldown timer para o trigger "oziell"
        self.last_oziell_time = 0

        # Lista de Admins
        admin_nicks_str = os.getenv("ADMIN_NICKS") 
        self.admin_nicks = [nick.strip().lower() for nick in admin_nicks_str.split(',')]
        print(f"[AUTH] Admins carregados: {self.admin_nicks}")

        # Configuração do WebSocket e Shutdown
        self.ws = None
        self.running = False
        self.auth.validate_and_refresh_token()
        signal.signal(signal.SIGINT, self._shutdown_handler)
        signal.signal(signal.SIGTERM, self._shutdown_handler)


    def _shutdown_handler(self, signum, frame):
        """Handler para shutdown gracioso com mensagem de despedida."""
        print("[INFO] Sinal de shutdown recebido. Enviando mensagem de despedida...")
        
        # Sinaliza para os threads das features pararem
        if self.comment_feature: self.comment_feature.stop_thread()
        if self.listen_feature: self.listen_feature.stop_thread()
        if self.cookie_system: self.cookie_system.stop_thread()

        goodbye_msg = "Bedge"
        for channel in self.auth.channels:
            self.send_message(channel, goodbye_msg)
            time.sleep(1)
        print("[INFO] Mensagem enviada. Encerrando...")
        if self.ws:
            self.ws.close()
        sys.exit(0)

    def send_message(self, channel, message):
        """Envia mensagem via WebSocket."""
        if self.ws and self.ws.sock and self.ws.sock.connected:
            full_msg = f"PRIVMSG #{channel} :{message}\r\n"
            self.ws.send(full_msg)
            print(f"[BOT] {channel}: {message}")
        else:
            print(f"[ERROR] WebSocket nao conectado. Nao foi possivel enviar: {message}")
    
    def _send_message_part(self, channel, part, delay):
        """[HELPER] Espera (em um thread) e envia uma parte da mensagem."""
        try:
            time.sleep(delay)
            self.send_message(channel, part)
        except Exception as e:
            print(f"[ERROR] Falha ao enviar parte da mensagem no thread: {e}")

    def send_long_message(self, channel, message, max_length=450, split_delay_sec=3):
        """
        Envia uma mensagem para o canal, dividindo-a em partes se exceder 
        'max_length'. Usa threads para os delays não bloquearem o bot.
        """
        if len(message) <= max_length:
            self.send_message(channel, message)
            return

        print(f"[INFO] Resposta longa detectada ({len(message)} chars). Dividindo em partes...")
        
        words = message.split()
        parts = []
        current_part = ""

        for word in words:
            if len(current_part) + len(word) + 1 > max_length:
                if current_part: 
                    parts.append(current_part.strip())
                current_part = word + " "
            else:
                current_part += word + " "
        
        if current_part:
            parts.append(current_part.strip())

        current_delay = 0
        for i, part in enumerate(parts):
            part_with_indicator = f"({i+1}/{len(parts)}) {part}"
            
            if len(part_with_indicator) > max_length:
                part_with_indicator = part[:max_length-10] + "..."

            t = threading.Thread(target=self._send_message_part, 
                                 args=(channel, part_with_indicator, current_delay))
            t.daemon = True
            t.start()
            
            current_delay += split_delay_sec

    def on_message(self, ws, message):
        """Handler de mensagens IRC (usa o cliente LLM)."""
        if message.startswith("PING"):
            ws.send("PONG :tmi.twitch.tv\r\n")
            return

        if "PRIVMSG" in message:
            
            try:
                if message.startswith("@"):
                    tags_part, message_part = message.split(" :", 1)
                else:
                    message_part = message

                author_part = message_part.split("!")[0].strip()
                
                channel_part = message_part.split("#")[1]
                channel = channel_part.split(" :")[0].strip()
                
                content = channel_part.split(" :", 1)[1].strip()

            except Exception as e:
                return

            # Log apenas do chat formatado
            print(f"[CHAT] {author_part}: {content}")
            
            content_lower = content.lower()

            # Histórico recente
            msg_data = {
                'timestamp': time.time(),
                'author': author_part,
                'content': content
            }
            if channel in self.recent_messages:
                self.recent_messages[channel].append(msg_data)

            if content == "!test_duplicate":
                print("[DEBUG] Simulando mensagem duplicada para teste...")
                self.on_message(ws, message)
                return
            
            try:
                self.training_logger.log_interaction(channel, author_part, content, None)
            except Exception as e:
                print(f"[ERROR] Falha ao salvar registro de captura: {e}")

            if author_part.lower() == self.auth.bot_nick.lower():
                return
            
            # 1. PROCESSA COMANDOS E TRIGGERS PRIMEIRO

            if content_lower == 'glorp':
                self.send_message(channel, 'glorp')
                return

            if content_lower.startswith("!glorp 8ball"):
                question = content[len("!glorp 8ball"):].strip()
                if not question:
                    self.send_message(channel, f"@{author_part}, você precisa me perguntar algo! glorp")
                    return
                self.eight_ball_feature.get_8ball_response(question, channel, author_part)
                return
            
            if content_lower == "!glorp cookie":
                if self.fortune_cookie_feature:
                    self.fortune_cookie_feature.get_fortune(channel, author_part)
                return

            if content_lower.startswith("!glorp slots"):
                if self.slots_feature:
                    parts = content.split()
                    bet = 10 # Default
                    if len(parts) > 2:
                        try:
                            bet = int(parts[2])
                        except ValueError:
                            pass
                    
                    result_msg = self.slots_feature.play(channel, author_part, bet)
                    self.send_message(channel, result_msg)
                return

            if content_lower.startswith("!glorp balance"):
                if self.cookie_system:
                    parts = content.split()
                    target_nick = author_part.lower()
                    if len(parts) > 2:
                        target_nick = parts[2].lower().replace("@", "")
                    
                    # Ignora se o alvo for o próprio bot
                    if target_nick == self.auth.bot_nick.lower():
                        return

                    count = self.cookie_system.get_cookies(target_nick)
                    if target_nick == author_part.lower():
                        self.send_message(channel, f"@{author_part}, você tem {count} cookies! glorp")
                    else:
                        self.send_message(channel, f"@{author_part}, o usuário {target_nick} tem {count} cookies! glorp")
                return

            if content_lower == "!glorp leaderboard":
                if self.cookie_system:
                    top_users = self.cookie_system.get_leaderboard(5)
                    if not top_users:
                        self.send_message(channel, "glorp Ainda não há barões dos cookies! Sadge")
                    else:
                        msg_parts = []
                        for i, (nick, count) in enumerate(top_users):
                            msg_parts.append(f"#{i+1} {nick} [{count} 🍪]")
                        
                        final_msg = "Barões dos Cookies: " + " , ".join(msg_parts)
                        self.send_message(channel, f"glorp {final_msg}")
                return

            if content_lower.startswith("!glorp help"):
                parts = content.split()
                if len(parts) < 3:
                    self.send_message(channel, "glorp Use !glorp help [comando] para saber mais. Ex: !glorp help slots")
                    return
                
                cmd_help = parts[2].lower()
                
                help_messages = {
                    "check": "glorp checa o status das features de chat (chat/comment/listen)",
                    "slots": "glorp use !glorp slots [valor] para apostar nos slots, aposta minima 10 🍪 caso não passe o valor",
                    "8ball": "glorp Pergunte ao oráculo! Ex: !glorp 8ball Vai chover?",
                    "cookie": "glorp Pegue seu biscoito da sorte diário (e ganhe cookies bônus).",
                    "balance": "glorp Verifique seu saldo de cookies ou de outro usuário. Ex: !glorp balance @nick",
                    "leaderboard": "glorp Mostra o top 5 usuários com mais cookies.",
                    "chat": "glorp (Admin) Ativa/Desativa a resposta a menções. Ex: !glorp chat on",
                    "listen": "glorp (Admin) Ativa/Desativa a escuta automática. Ex: !glorp listen on",
                    "comment": "glorp (Admin) Ativa/Desativa comentários automáticos. Ex: !glorp comment on",
                    "scan": "glorp (Admin) Força uma escuta manual de 15s. Ex: !glorp scan",
                    "addcookie": "glorp (Admin) Adiciona cookies. Ex: !glorp addcookie nick 100",
                    "removecookie": "glorp (Admin) Remove cookies. Ex: !glorp removecookie nick 100",
                    "commands": "glorp Lista todos os comandos disponíveis.",
                    "help": "Você deve estar precisando mesmo nise"
                }
                
                msg = help_messages.get(cmd_help, f"glorp Comando '{cmd_help}' não encontrado. Tente !glorp commands.")
                self.send_message(channel, msg)
                return

            # Comandos de Admin
            if content.startswith("!glorp"):
                if author_part.lower() in self.admin_nicks:
                    self.handle_admin_command(content, channel)
                    return
                else:
                    self.send_message(channel, f"@{author_part}, comando apenas para os chegados arnoldHalt")
                    return
            
            # 2. SE NÃO FOR COMANDO, CHECA DUPLICATAS DE CHAT
            unique_message_identifier = f"{author_part}-{channel}-{content}"
            message_hash = hash(unique_message_identifier)

            if message_hash in self.processed_message_ids:
                # Log de duplicata removido para limpeza
                return
            self.processed_message_ids.append(message_hash)

            # 3. SE NÃO FOR COMANDO NEM DUPLICATA, PROCESSA MENÇÕES À IA
            if self.chat_enabled and self.auth.bot_nick.lower() in content.lower():
                print(f"[DEBUG] Bot mencionado por {author_part}. Gerando resposta...")
                
                # Concede +1 cookie por Interação Direta (Menção)
                if self.cookie_system:
                    self.cookie_system.handle_interaction(author_part.lower())

                try:
                    # Log da query já feito pelo training_logger acima
                    
                    recent_history = self.recent_messages.get(channel)
                    
                    if self.gemini_client and self.memory_mgr:
                        response = self.gemini_client.get_response(
                            content, 
                            channel, 
                            author_part, 
                            self.memory_mgr,
                            recent_history 
                        )
                        
                        if response:
                            self.send_long_message(channel, response)
                except Exception as e:
                    print(f"[ERROR] Falha ao gerar resposta: {e}")
            
            # 4. PROCESSA O GATILHO DO COMMENT
            if self.comment_feature:
                # Passa o author_part para receber o prêmio de 10 cookies se o trigger ativar
                self.comment_feature.roll_for_comment(channel, author_part)
            
    def handle_admin_command(self, command, channel):
        """
        Processa comandos de admin e DELEGA para as classes de feature apropriadas.
        """
        parts = command.split()
        
        # Comandos de 2 partes
        if len(parts) == 2:
            command_name = parts[1].lower()

            if command_name == "check":
                chat_status = "ATIVADO" if self.chat_enabled else "DESATIVADO"
                listen_status = self.listen_feature.get_status()
                comment_status = self.comment_feature.get_status() 
                
                status_msg = (
                    f"Status: "
                    f"Chat peepoChat  {chat_status} | "
                    f"Listen glorp 📡  {listen_status} | "
                    f"Comment peepoTalk {comment_status}"
                )
                self.send_message(channel, status_msg)
                return
            
            elif command_name == "commands":
                self.send_message(channel, "glorp 👉 check, chat/listen/comment [on/off], scan, 8ball [pergunta], cookie, balance, leaderboard, slots [aposta], help [comando]")
                return
            
            elif command_name == "scan":
                self.listen_feature.trigger_manual_scan(channel)
                return
        
        if len(parts) == 4 and self.cookie_system:
            command_name = parts[1].lower()
            target_nick = parts[2].lower().replace("@", "")
            
            try:
                amount = int(parts[3])
                if amount <= 0:
                    self.send_message(channel, "glorp A quantia deve ser maior que zero!")
                    return

                if command_name == "addcookie":
                    self.cookie_system.add_cookies(target_nick, amount)
                    self.send_message(channel, f"glorp {amount} cookies adicionados para {target_nick}.")
                    return
                
                elif command_name == "removecookie":
                    self.cookie_system.remove_cookies(target_nick, amount)
                    self.send_message(channel, f"glorp {amount} cookies removidos de {target_nick}.")
                    return
                    
            except ValueError:
                self.send_message(channel, "glorp A quantia de cookies deve ser um número!")
                return
            except Exception as e:
                logging.error(f"[AdminCookie] Falha no comando: {e}")
                self.send_message(channel, "glorp Ocorreu um erro ao modificar os cookies.")
                return

        # Comandos On/Off (3 partes)
        if len(parts) == 3:
            feature = parts[1].lower()
            state = (parts[2].lower() == "on") # Converte para True ou False

            if feature == "chat":
                self.chat_enabled = state
                status = "ATIVADO" if self.chat_enabled else "DESATIVADO"
                self.send_message(channel, f"peepoChat O modo CHAT foi {status}.")
                return
            
            elif feature == "listen":
                self.listen_feature.set_enabled(state)
                status = self.listen_feature.get_status()
                self.send_message(channel, f"glorp 📡 O modo LISTEN foi {status}.")
                return
            
            elif feature == "comment":
                self.comment_feature.set_enabled(state)
                status = self.comment_feature.get_status() 
                self.send_message(channel, f"peepoTalk O modo COMMENT foi {status}.")
                return
        
        # Se nenhum comando de 2 ou 3 partes foi pego
        self.send_message(channel, "Comando invalido. Use: !glorp <feature> <on/off>, !glorp check ou !glorp commands para mais informações glorp")


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
            time.sleep(2) # Adiciona um delay de 2s entre joins
            self.send_message(channel, "Wokege")

    def on_error(self, ws, error):
        """Handler para erros do WebSocket."""
        print(f"[ERROR] WebSocket error: {error}")

    def on_close(self, ws, close_status_code, close_msg):
        """Handler para quando a conexao WebSocket é fechada."""
        print(f"[INFO] Conexao WebSocket fechada. Codigo: {close_status_code}, Msg: {close_msg}")


if __name__ == "__main__":
    bot = TwitchIRC()
    bot.run()