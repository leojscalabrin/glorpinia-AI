"""Persistent XP and RPG classes for Glorpinia."""
import json, logging, math, os, random, threading, time

CLASS_POOL = [
 ("Tecelão do Vazio", "Manipula coincidências e fendas entre mundos."),
 ("Cavaleiro de Cookies", "Transforma generosidade e dívidas em poder arcano."),
 ("Oráculo Caótico", "Enxerga padrões improváveis e prevê desastres."),
 ("Druida de Neon", "Canaliza a energia viva do chat."),
 ("Engenheiro de Relíquias", "Improvisa soluções com artefatos impossíveis."),
 ("Bardo da Entropia", "Converte memes e caos em magia."),
 ("Sentinela Estelar", "Protege aliados durante colapsos galáticos."),
 ("Alquimista de Ecos", "Mistura lembranças e palavras em efeitos inesperados."),
 ("Ladino das Probabilidades", "Rouba oportunidades do azar."),
 ("Invocador de Glitches", "Convoca falhas da realidade."),
 ("Monge do Lag", "Transforma atrasos em vantagem."),
 ("Caçador de Relíquias", "Segue pistas e fareja tesouros perdidos."),
]

class UserRPGManager:
    DEFAULT_FILE = "user_rpg.json"
    MESSAGE_XP = 2
    MESSAGE_COOLDOWN_SECONDS = 60
    MAX_MESSAGE_XP_PER_DAY = 120
    MAX_COOKIE_XP_PER_EVENT = 25

    def __init__(self, path=None):
        self.path = path or os.getenv("USER_RPG_FILE", self.DEFAULT_FILE)
        self._lock = threading.RLock()
        self._users = {}
        self._last_message_xp = {}
        self._daily_message_xp = {}
        self._load()

    @staticmethod
    def _nick(nick):
        return (nick or "").strip().lstrip("@").lower()

    def _load(self):
        if not os.path.exists(self.path): return
        try:
            with open(self.path, encoding="utf-8") as f: data = json.load(f)
            if isinstance(data, dict):
                self._users = {self._nick(k): v for k, v in data.items() if self._nick(k) and isinstance(v, dict)}
        except Exception as exc: logging.error("[RPG] Falha ao carregar %s: %s", self.path, exc)

    def _save(self):
        with open(self.path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(self._users, f, ensure_ascii=False, indent=2)
        os.replace(self.path + ".tmp", self.path)

    @staticmethod
    def xp_to_next(level):
        if level < 100: return int(80 + level * 24 + level ** 1.35 * 3)
        return int(2800 + (level - 99) ** 1.55 * 115)

    def _ensure(self, nick):
        nick = self._nick(nick)
        if not nick: return None
        return self._users.setdefault(nick, {"xp": 0, "level": 1, "class_options": [],
            "class_name": None, "class_description": None, "lore": None, "evolved": False,
            "last_channel": None, "last_message_at": 0})

    def _level_for_xp(self, xp):
        level, remaining = 1, max(0, int(xp))
        while level < 500 and remaining >= self.xp_to_next(level):
            remaining -= self.xp_to_next(level)
            level += 1
        return level

    def _add_xp_locked(self, nick, amount, channel=None):
        p = self._ensure(nick)
        if not p: return None
        old = int(p.get("level", 1))
        p["xp"] = max(0, int(p.get("xp", 0)) + int(amount))
        p["level"] = self._level_for_xp(p["xp"])
        if channel:
            p["last_channel"] = channel.lower().lstrip("#")
            p["last_message_at"] = time.time()
        if p["level"] >= 10 and old < 10 and not p.get("class_name") and not p.get("class_options"):
            p["class_options"] = [{"name": n, "description": d} for n, d in random.sample(CLASS_POOL, 3)]
        if p["level"] >= 100 and p.get("class_name") and not p.get("evolved"):
            p["evolved"] = True
            p["evolved_class_name"] = p["class_name"] + " Ascendente"
            p["evolved_description"] = "Uma forma desperta, mais rara e poderosa do seu arquétipo original."
        self._save()
        return {"old_level": old, "level": p["level"], "leveled": p["level"] > old, "profile": dict(p)}

    def add_xp(self, nick, amount, channel=None):
        if not nick or not amount: return None
        with self._lock: return self._add_xp_locked(nick, amount, channel)

    def record_message(self, nick, channel, is_command=False):
        if not self._nick(nick): return None
        now, key = time.time(), self._nick(nick)
        day = time.strftime("%Y-%m-%d", time.gmtime(now))
        with self._lock:
            p = self._ensure(key)
            if p:
                p["last_channel"], p["last_message_at"] = channel.lower().lstrip("#"), now
            if is_command:
                self._save()
                return None
            last, daily_key = self._last_message_xp.get(key, 0), (key, day)
            daily = self._daily_message_xp.get(daily_key, 0)
            if now - last < self.MESSAGE_COOLDOWN_SECONDS or daily >= self.MAX_MESSAGE_XP_PER_DAY:
                if p:
                    self._save()
                return None
            self._last_message_xp[key] = now
            self._daily_message_xp[daily_key] = daily + self.MESSAGE_XP
            return self._add_xp_locked(key, self.MESSAGE_XP, channel)

    def record_cookie_change(self, nick, amount, gained=True):
        try: amount = max(0, int(amount))
        except (TypeError, ValueError): return None
        if not amount: return None
        points = min(self.MAX_COOKIE_XP_PER_EVENT, max(1, int(math.log2(amount + 1) * 2.5)))
        return self.add_xp(nick, points if gained else -max(1, points // 2))

    def choose_class(self, nick, choice):
        with self._lock:
            p = self._ensure(nick)
            if not p or p.get("level", 1) < 10: return False, "level", None
            if p.get("class_name"): return False, "chosen", dict(p)
            try: index = int(choice) - 1
            except (TypeError, ValueError): return False, "choice", dict(p)
            options = p.get("class_options") or []
            if index not in range(len(options)): return False, "choice", dict(p)
            selected = options[index]
            p.update(class_name=selected["name"], class_description=selected["description"], class_options=[], lore=None)
            self._save()
            return True, "chosen", dict(p)

    def set_lore(self, nick, lore):
        with self._lock:
            p = self._ensure(nick)
            if not p or not p.get("class_name"): return False
            p["lore"] = (lore or "").strip()[:900]
            self._save()
            return True
