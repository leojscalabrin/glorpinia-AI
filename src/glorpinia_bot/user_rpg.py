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
    MESSAGE_XP = 1
    DIRECT_MENTION_XP = 3
    COMMENT_MENTION_XP = 2
    MAX_COOKIE_XP_PER_EVENT = 25
    CLASS_OPTION_COUNT = 3
    CLASS_UNLOCK_LEVEL = 10
    # Nível a partir do qual as opções de classe começam a ser preparadas (antes do desbloqueio).
    CLASS_PREP_LEVEL = max(1, min(10, int(os.getenv("CLASS_PREP_LEVEL", "8"))))

    def __init__(self, path=None):
        self.path = path or os.getenv("USER_RPG_FILE", self.DEFAULT_FILE)
        self._lock = threading.RLock()
        self._users = {}
        # Callable(nick, channel) chamado, sem bloquear, quando alguém precisa de opções de classe.
        self.class_options_hook = None
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
        """XP para o próximo nível; curva ajustada para cookies com conversão de 1:1."""
        level = max(1, int(level))
        # Total de 1.200 XP do nível 1 ao 10; valores maiores amortecem bônus grandes de cookies.
        early_levels = (60, 70, 80, 100, 120, 140, 170, 210, 250)
        if level <= 9:
            return early_levels[level - 1]
        if level < 100:
            distance = level - 10
            return int(250 + distance * 18 + distance ** 1.5 * 0.6)
        return int(2500 + (level - 99) ** 1.7 * 90)

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

    def _add_xp_locked(self, nick, amount, channel=None, reason="recompensa RPG"):
        p = self._ensure(nick)
        if not p: return None
        old = int(p.get("level", 1))
        xp_before = int(p.get("xp", 0))
        p["xp"] = max(0, xp_before + int(amount))
        p["level"] = self._level_for_xp(p["xp"])
        applied = p["xp"] - xp_before
        # INFO para aparecer no journal mesmo quando o serviço não habilita DEBUG.
        logging.info(
            "[RPG][XP] nick=%s motivo=%s solicitado=%+d aplicado=%+d xp=%d->%d level=%d->%d",
            self._nick(nick), reason, int(amount), applied, xp_before, p["xp"], old, p["level"]
        )
        if channel:
            p["last_channel"] = channel.lower().lstrip("#")
            p["last_message_at"] = time.time()
        if p["level"] >= self.CLASS_PREP_LEVEL and not p.get("class_name") and not p.get("class_options"):
            hook = self.class_options_hook
            if hook:
                # O gancho só agenda o trabalho em outra thread; nunca bloqueia o fluxo de XP.
                try: hook(self._nick(nick), p.get("last_channel"))
                except Exception as exc: logging.error("[RPG] Falha no gancho de opções de classe: %s", exc)
            elif p["level"] >= self.CLASS_UNLOCK_LEVEL and old < self.CLASS_UNLOCK_LEVEL:
                self._store_class_options_locked(p, self._pool_options(), "pool")
        if p["level"] >= 100 and p.get("class_name") and not p.get("evolved"):
            p["evolved"] = True
            p["evolved_class_name"] = p["class_name"] + " Ascendente"
            p["evolved_description"] = "Uma forma desperta, mais rara e poderosa do seu arquétipo original."
        self._save()
        return {"old_level": old, "level": p["level"], "leveled": p["level"] > old, "profile": dict(p)}

    def add_xp(self, nick, amount, channel=None, reason="recompensa RPG"):
        if not nick or not amount: return None
        with self._lock: return self._add_xp_locked(nick, amount, channel, reason)

    def record_message(self, nick, channel, is_command=False):
        if not self._nick(nick): return None
        key = self._nick(nick)
        with self._lock:
            p = self._ensure(key)
            if p:
                p["last_channel"], p["last_message_at"] = channel.lower().lstrip("#"), time.time()
            if is_command:
                self._save()
                return None
            # Cada mensagem normal concede XP; não há cooldown nem limite diário.
            return self._add_xp_locked(key, self.MESSAGE_XP, channel, reason="mensagem no chat")

    def record_cookie_change(self, nick, amount, gained=True):
        try: amount = max(0, int(amount))
        except (TypeError, ValueError): return None
        if not amount: return None
        # Ganhos de cookies convertem 1:1 em XP, sem teto por evento.
        # Perdas mantêm a penalidade reduzida anterior para não zerar XP por uma transferência.
        points = min(self.MAX_COOKIE_XP_PER_EVENT, max(1, int(math.log2(amount + 1) * 2.5)))
        delta = amount if gained else -max(1, points // 2)
        reason = f"cookies {'ganhos' if gained else 'perdidos'} ({amount}; conversão {'1:1' if gained else 'penalidade reduzida'})"
        return self.add_xp(nick, delta, reason=reason)

    def choose_class(self, nick, choice):
        with self._lock:
            p = self._ensure(nick)
            if not p or p.get("level", 1) < 10: return False, "level", None
            if p.get("class_name"): return False, "chosen", dict(p)
            try: index = int(choice) - 1
            except (TypeError, ValueError): return False, "choice", dict(p)
            options = p.get("class_options") or []
            if not options: return False, "no_options", dict(p)
            if index not in range(len(options)): return False, "choice", dict(p)
            selected = options[index]
            p.update(class_name=selected["name"], class_description=selected["description"], class_options=[], lore=None)
            p.pop("class_options_source", None)
            if p.get("level", 1) >= 100:
                p["evolved"] = True
                p["evolved_class_name"] = p["class_name"] + " Ascendente"
                p["evolved_description"] = "Uma forma desperta, mais rara e poderosa do seu arquétipo original."
            self._save()
            return True, "chosen", dict(p)

    @classmethod
    def _pool_options(cls):
        return [{"name": n, "description": d} for n, d in random.sample(CLASS_POOL, cls.CLASS_OPTION_COUNT)]

    def _store_class_options_locked(self, p, options, source):
        p["class_options"] = options
        p["class_options_source"] = source
        self._save()
        logging.info("[RPG][Classes] opções definidas (fonte=%s): %s", source, [o["name"] for o in options])

    def needs_class_options(self, nick):
        """True se a pessoa já está na faixa de preparo, não tem classe e não tem opções."""
        with self._lock:
            p = self._users.get(self._nick(nick))
            return bool(p and int(p.get("level", 1)) >= self.CLASS_PREP_LEVEL
                        and not p.get("class_name") and not p.get("class_options"))

    def set_class_options(self, nick, options, source="ai"):
        """Grava opções prontas. Nunca sobrescreve opções existentes nem classe já escolhida."""
        try:
            clean = [{"name": str(o["name"]).strip(), "description": str(o["description"]).strip()} for o in options]
        except (TypeError, KeyError):
            return False
        if len(clean) != self.CLASS_OPTION_COUNT or not all(o["name"] and o["description"] for o in clean):
            return False
        with self._lock:
            p = self._users.get(self._nick(nick))
            if not p or p.get("class_name") or p.get("class_options"): return False
            if int(p.get("level", 1)) < self.CLASS_PREP_LEVEL: return False
            self._store_class_options_locked(p, clean, source)
            return True

    def assign_fallback_class_options(self, nick):
        """Sorteia 3 classes da pool fixa. Só vale para quem já desbloqueou a escolha (nível 10+)."""
        with self._lock:
            p = self._users.get(self._nick(nick))
            if not p or int(p.get("level", 1)) < self.CLASS_UNLOCK_LEVEL: return False
            if p.get("class_name") or p.get("class_options"): return False
            self._store_class_options_locked(p, self._pool_options(), "pool")
            return True

    def set_lore(self, nick, lore):
        with self._lock:
            p = self._ensure(nick)
            if not p or not p.get("class_name"): return False
            p["lore"] = (lore or "").strip()[:900]
            self._save()
            return True


    def get_profile(self, nick):
        """Return a copy of a user RPG profile, or None if the user has no profile yet."""
        key = self._nick(nick)
        if not key:
            return None
        with self._lock:
            profile = self._users.get(key)
            return dict(profile) if profile is not None else None

    def get_ranking(self, limit=5):
        """Return profiles ordered by level, then total XP, descending."""
        try:
            limit = max(0, int(limit))
        except (TypeError, ValueError):
            limit = 5
        with self._lock:
            ordered = sorted(
                self._users.items(),
                key=lambda item: (
                    int(item[1].get("level", 1)),
                    int(item[1].get("xp", 0)),
                    item[0],
                ),
                reverse=True,
            )
            return [(nick, dict(profile)) for nick, profile in ordered[:limit]]
