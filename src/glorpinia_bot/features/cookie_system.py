import sqlite3
import os
import threading
import time
import logging

class CookieSystem:
    def __init__(self, bot):
        """
        Inicializa o sistema de cookies (moeda).
        'bot' é a instância principal do TwitchIRC.
        """
        print("[Feature] CookieSystem Initialized.")
        self.bot = bot
        self.db_path = "glorpinia_cookies.db"
        self._initialize_db()
        
        # --- Lógica do Bônus Diário ---
        self.timer_running = True
        self.last_bonus_time = 0
        self.thread = threading.Thread(target=self._daily_bonus_thread, daemon=True)
        self.thread.start()

    def _initialize_db(self):
        """Cria a tabela de cookies se ela não existir."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                c = conn.cursor()
                c.execute("""
                    CREATE TABLE IF NOT EXISTS user_cookies (
                        user_nick TEXT PRIMARY KEY,
                        cookie_count INTEGER NOT NULL DEFAULT 0
                    )
                """)
                conn.commit()
        except Exception as e:
            logging.error(f"[CookieSystem] Falha ao inicializar o banco de dados: {e}")

    def stop_thread(self):
        """Sinaliza para o thread parar (usado no shutdown)."""
        self.timer_running = False

    def _daily_bonus_thread(self):
        """Thread que concede 5 cookies a todos no DB a cada 24h."""
        self.last_bonus_time = time.time()
        
        while self.timer_running:
            time.sleep(3600) # Checa a cada hora
            
            now = time.time()
            if (now - self.last_bonus_time) > 86400: # 24h
                logging.info("[CookieSystem] Aplicando bônus diário de 5 cookies...")
                try:
                    with sqlite3.connect(self.db_path) as conn:
                        c = conn.cursor()
                        c.execute("UPDATE user_cookies SET cookie_count = cookie_count + 5")
                        conn.commit()
                    self.last_bonus_time = now
                    logging.info("[CookieSystem] Bônus diário aplicado com sucesso.")
                except Exception as e:
                    logging.error(f"[CookieSystem] Falha ao aplicar bônus diário: {e}")

    def _check_or_create_user(self, nick: str):
        """Garante que um usuário exista no DB. (Interno)"""
        nick = nick.lower()
        try:
            with sqlite3.connect(self.db_path) as conn:
                c = conn.cursor()
                c.execute("INSERT OR IGNORE INTO user_cookies (user_nick, cookie_count) VALUES (?, 0)", (nick,))
                conn.commit()
        except Exception as e:
            logging.error(f"[CookieSystem] Falha ao checar/criar usuário {nick}: {e}")

    def get_cookies(self, nick: str) -> int:
        """Busca a contagem de cookies de um usuário."""
        nick = nick.lower()
        self._check_or_create_user(nick)
        try:
            with sqlite3.connect(self.db_path) as conn:
                c = conn.cursor()
                c.execute("SELECT cookie_count FROM user_cookies WHERE user_nick = ?", (nick,))
                result = c.fetchone()
                return result[0] if result else 0
        except Exception as e:
            logging.error(f"[CookieSystem] Falha ao buscar cookies para {nick}: {e}")
            return 0

    def get_leaderboard(self, limit=5):
        """
        Retorna os top N usuários com mais cookies, EXCLUINDO o próprio bot.
        """
        try:
            bot_nick = self.bot.auth.bot_nick.lower()
            with sqlite3.connect(self.db_path) as conn:
                c = conn.cursor()
                c.execute(
                    "SELECT user_nick, cookie_count FROM user_cookies WHERE user_nick != ? ORDER BY cookie_count DESC LIMIT ?", 
                    (bot_nick, limit)
                )
                return c.fetchall()
        except Exception as e:
            logging.error(f"[CookieSystem] Falha ao buscar leaderboard: {e}")
            return []

    def add_cookies(self, nick: str, amount_to_add: int):
        """Adiciona cookies a um usuário."""
        nick = nick.lower()
        self._check_or_create_user(nick)
        try:
            with sqlite3.connect(self.db_path) as conn:
                c = conn.cursor()
                c.execute("UPDATE user_cookies SET cookie_count = cookie_count + ? WHERE user_nick = ?", (amount_to_add, nick))
                conn.commit()
            logging.info(f"[CookieSystem] +{amount_to_add} cookies para {nick}.")
        except Exception as e:
            logging.error(f"[CookieSystem] Falha ao adicionar cookies para {nick}: {e}")

    def remove_cookies(self, nick: str, amount_to_remove: int):
        """Remove cookies de um usuário."""
        nick = nick.lower()
        self._check_or_create_user(nick)
        try:
            with sqlite3.connect(self.db_path) as conn:
                c = conn.cursor()
                c.execute("UPDATE user_cookies SET cookie_count = MAX(0, cookie_count - ?) WHERE user_nick = ?", (amount_to_remove, nick))
                conn.commit()
            logging.info(f"[CookieSystem] -{amount_to_remove} cookies para {nick}.")
        except Exception as e:
            logging.error(f"[CookieSystem] Falha ao remover cookies de {nick}: {e}")

    def handle_interaction(self, nick: str):
        """Concede +1 cookie por interação."""
        nick = nick.lower()
        try:
            with sqlite3.connect(self.db_path) as conn:
                c = conn.cursor()
                c.execute("""
                    INSERT INTO user_cookies (user_nick, cookie_count) VALUES (?, 1)
                    ON CONFLICT(user_nick) DO UPDATE SET cookie_count = cookie_count + 1
                """, (nick,))
                conn.commit()
        except Exception as e:
            logging.error(f"[CookieSystem] Falha ao dar cookie de interação para {nick}: {e}")