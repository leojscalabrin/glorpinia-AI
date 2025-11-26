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
        
        self.FORBIDDEN_NICKS = {
            "system", "usuario", "user", "usuário", "você", "eu", "everyone", "here", "chat"
        }

        self._initialize_db()
        
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
    
    def _is_nick_valid(self, nick: str) -> bool:
        """Retorna False se o nick estiver na lista negra ou for inválido."""
        if not nick: return False
        clean = nick.lower().strip().replace("@", "")
        if clean in self.FORBIDDEN_NICKS:
            logging.warning(f"[CookieSystem] Transação bloqueada para nick proibido: '{clean}'")
            return False
        return True

    def _daily_bonus_thread(self):
        """Thread que concede 5 cookies a todos no DB a cada 24h."""
        self.last_bonus_time = time.time()
        
        while self.timer_running:
            time.sleep(3600)
            
            now = time.time()
            if (now - self.last_bonus_time) > 86400:
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
        if not self._is_nick_valid(nick): return
        
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
        Retorna os top N usuários com mais cookies, EXCLUINDO o próprio bot e proibidos.
        """
        try:
            bot_nick = self.bot.auth.bot_nick.lower()
            forbidden_placeholders = ','.join(['?'] * len(self.FORBIDDEN_NICKS))
            query_args = [bot_nick] + list(self.FORBIDDEN_NICKS) + [limit]
            
            query = f"""
                SELECT user_nick, cookie_count 
                FROM user_cookies 
                WHERE user_nick != ? 
                AND user_nick NOT IN ({forbidden_placeholders})
                ORDER BY cookie_count DESC 
                LIMIT ?
            """
            
            with sqlite3.connect(self.db_path) as conn:
                c = conn.cursor()
                c.execute(query, query_args)
                return c.fetchall()
        except Exception as e:
            logging.error(f"[CookieSystem] Falha ao buscar leaderboard: {e}")
            return []

    def add_cookies(self, nick: str, amount_to_add: int):
        """Adiciona cookies a um usuário."""
        if not self._is_nick_valid(nick): return
        
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
        """
        Remove cookies de um usuário e TRANSFERE para a conta do bot.
        """
        if not self._is_nick_valid(nick): return
        
        nick = nick.lower()
        bot_nick = self.bot.auth.bot_nick.lower()
        
        if nick == bot_nick: return

        self._check_or_create_user(nick)
        self._check_or_create_user(bot_nick) 
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                c = conn.cursor()
                
                c.execute("SELECT cookie_count FROM user_cookies WHERE user_nick = ?", (nick,))
                result = c.fetchone()
                current_balance = result[0] if result else 0
                
                actual_removed = min(current_balance, amount_to_remove)
                
                if actual_removed > 0:
                    c.execute("UPDATE user_cookies SET cookie_count = cookie_count - ? WHERE user_nick = ?", (actual_removed, nick))
                    c.execute("UPDATE user_cookies SET cookie_count = cookie_count + ? WHERE user_nick = ?", (actual_removed, bot_nick))
                    conn.commit()
                    logging.info(f"[CookieSystem] Transferidos {actual_removed} cookies de {nick} para {bot_nick}.")
                else:
                    logging.info(f"[CookieSystem] {nick} não tinha cookies suficientes para remover.")
                    
        except Exception as e:
            logging.error(f"[CookieSystem] Falha ao remover/transferir cookies de {nick}: {e}")

    def handle_interaction(self, nick: str):
        """Concede +1 cookie por interação."""
        if not self._is_nick_valid(nick): return
        
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