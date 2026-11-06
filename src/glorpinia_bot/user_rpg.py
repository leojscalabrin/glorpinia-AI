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
    COOKIE_REWARD_BASE_MIN = 1
    COOKIE_REWARD_BASE_MAX = 10
    COOKIE_REWARD_LEVEL_DIVISOR = 3
    COOKIE_REWARD_LEVEL_MULTIPLIER = 2
    AI_COOKIE_CAP_BASE = 999
    AI_COOKIE_CAP_LEVEL_MULTIPLIER = 100

    def __init__(self, path=None):
        self.path = path or os.getenv("USER_RPG_FILE", self.DEFAULT_FILE)
        self._lock = threading.RLock()
        self._users = {}
        self._load()

    @staticmethod
    def _nick(nick):
        return (nick or "").strip().lstrip("@").lower()

    def _load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                logging.warning("[RPG] Arquivo %s não contém um objeto de perfis.", self.path)
                return

            migrated = 0
            loaded = {}
            for raw_nick, raw_profile in data.items():
                nick = self._nick(raw_nick)
                if not nick or not isinstance(raw_profile, dict):
                    continue
                profile = dict(raw_profile)
                try:
                    xp = max(0, int(profile.get("xp", 0)))
                except (TypeError, ValueError):
                    xp = 0
                stored_level = self._normalized_level(profile.get("level", 1))
                canonical_level = self._level_for_xp(xp)
                profile["xp"] = xp
                profile["level"] = canonical_level
                profile.setdefault("class_options", [])
                profile.setdefault("class_options_stage", None)
                profile.setdefault("definitive_class_options", [])
                profile.setdefault("definitive_class_options_ready", False)
                profile.setdefault("class_name", None)
                profile.setdefault("class_description", None)
                profile.setdefault("class_stage", None)
                profile.setdefault("class_provisional", False)
                profile.setdefault("lore", None)
                profile.setdefault("evolved", False)
                profile.setdefault("last_channel", None)
                profile.setdefault("last_message_at", 0)
                if stored_level != canonical_level:
                    migrated += 1
                    logging.warning(
                        "[RPG][MIGRATION] perfil=%s level_salvo=%s level_calculado=%s xp=%s; nível sincronizado sem conceder XP.",
                        nick, stored_level, canonical_level, xp,
                    )
                loaded[nick] = profile
            self._users = loaded
            if migrated:
                self._save()
                logging.info("[RPG][MIGRATION] %s perfis sincronizados com a curva atual.", migrated)
        except Exception as exc:
            logging.error("[RPG] Falha ao carregar %s: %s", self.path, exc)

    def _save(self):
        with open(self.path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(self._users, f, ensure_ascii=False, indent=2)
        os.replace(self.path + ".tmp", self.path)

    @staticmethod
    def xp_to_next(level):
        """XP para o próximo nível; curva ajustada para cookies com conversão de 1:1."""
        level = max(1, int(level))
        # Os primeiros dez níveis exigem 500 XP no total, com progressão gradual.
        early_levels = (30, 35, 40, 45, 50, 55, 60, 80, 105)
        if level <= 9:
            return early_levels[level - 1]
        if level < 100:
            distance = level - 10
            return int(250 + distance * 18 + distance ** 1.5 * 0.6)
        return int(2500 + (level - 99) ** 1.7 * 90)

    @staticmethod
    def _normalized_level(level):
        try:
            return max(1, min(500, int(level)))
        except (TypeError, ValueError):
            return 1

    @classmethod
    def cookie_reward_range(cls, level):
        """Faixa diária do *cookie; cresce suavemente com a participação acumulada."""
        level = cls._normalized_level(level)
        activity_steps = math.isqrt(level - 1)
        minimum = cls.COOKIE_REWARD_BASE_MIN + activity_steps // cls.COOKIE_REWARD_LEVEL_DIVISOR
        maximum = cls.COOKIE_REWARD_BASE_MAX + activity_steps * cls.COOKIE_REWARD_LEVEL_MULTIPLIER
        return minimum, max(minimum, maximum)

    @classmethod
    def ai_cookie_transaction_limit(cls, level):
        """Limite técnico por recompensa, escalonado pelo level do destinatário."""
        level = cls._normalized_level(level)
        return cls.AI_COOKIE_CAP_BASE + math.isqrt(level - 1) * cls.AI_COOKIE_CAP_LEVEL_MULTIPLIER

    def get_cookie_reward_range(self, nick):
        profile = self.get_profile(nick) or {}
        return self.cookie_reward_range(profile.get("level", 1))

    def get_ai_cookie_transaction_limit(self, nick):
        profile = self.get_profile(nick) or {}
        return self.ai_cookie_transaction_limit(profile.get("level", 1))

    def _ensure(self, nick):
        nick = self._nick(nick)
        if not nick: return None
        profile = self._users.setdefault(nick, {
            "xp": 0, "level": 1, "class_options": [], "class_options_stage": None,
            "definitive_class_options": [], "definitive_class_options_ready": False,
            "class_name": None, "class_description": None, "class_stage": None,
            "class_provisional": False, "lore": None, "evolved": False,
            "last_channel": None, "last_message_at": 0,
        })
        profile.setdefault("class_options", [])
        profile.setdefault("class_options_stage", None)
        profile.setdefault("definitive_class_options", [])
        profile.setdefault("definitive_class_options_ready", False)
        return profile

    def ensure_profile(self, nick):
        """Create and return a profile when a user explicitly opens their RPG sheet."""
        with self._lock:
            profile = self._ensure(nick)
            if not profile: return None
            self._save()
            return dict(profile)

    def set_class_options(self, nick, options, stage):
        """Persist three validated class choices for the requested progression stage."""
        if stage not in ("provisional", "definitive") or not isinstance(options, list) or len(options) != 3:
            return False
        normalized = []
        for item in options:
            if not isinstance(item, dict): return False
            name = str(item.get("name") or "").strip()[:60]
            description = str(item.get("description") or "").strip()[:180]
            if not name or not description: return False
            normalized.append({"name": name, "description": description})
        with self._lock:
            p = self._ensure(nick)
            if not p: return False
            if stage == "provisional" and int(p.get("level", 1)) >= 10: return False
            if stage == "definitive" and int(p.get("level", 1)) < 10: return False
            if stage == "provisional":
                p["class_options"] = normalized
                p["class_options_stage"] = stage
            else:
                p["definitive_class_options"] = normalized
                p["definitive_class_options_ready"] = True
                p["definitive_class_options_generated_at"] = time.time()
            self._save()
            return True

    def get_class_options(self, nick, stage):
        with self._lock:
            profile = self._users.get(self._nick(nick))
            if not profile:
                return []
            if stage == "definitive":
                return list(profile.get("definitive_class_options") or [])
            if profile.get("class_options_stage") == "provisional":
                return list(profile.get("class_options") or [])
            return []

    def needs_class_options(self, nick, stage="definitive", minimum_level=8):
        with self._lock:
            profile = self._users.get(self._nick(nick))
            if not profile:
                return False
            level = self._normalized_level(profile.get("level", 1))
            if stage == "definitive":
                return (
                    level >= minimum_level
                    and not (profile.get("class_name") and not profile.get("class_provisional"))
                    and not profile.get("definitive_class_options_ready")
                )
            return level <= 9 and not self.get_class_options(nick, "provisional")

    def assign_fallback_class_options(self, nick, stage="definitive"):
        options = [
            {"name": name, "description": description}
            for name, description in random.sample(CLASS_POOL, 3)
        ]
        return self.set_class_options(nick, options, stage)

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
        logging.info(
            "[RPG][XP] nick=%s motivo=%s solicitado=%+d aplicado=%+d xp=%d->%d level=%d->%d",
            self._nick(nick), reason, int(amount), applied, xp_before, p["xp"], old, p["level"]
        )
        if channel:
            p["last_channel"] = channel.lower().lstrip("#")
            p["last_message_at"] = time.time()
        # As opções definitivas são geradas sob demanda pelo comando *class,
        # com contexto recente do usuário, em vez de usar um sorteio genérico aqui.
        if p["level"] >= 10 and old < 10 and p.get("class_provisional"):
            p["class_options"] = []
            p["class_options_stage"] = None
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
            return self._add_xp_locked(key, self.MESSAGE_XP, channel, reason="mensagem no chat")

    def record_cookie_change(self, nick, amount, gained=True):
        try: amount = max(0, int(amount))
        except (TypeError, ValueError): return None
        if not amount or not gained:
            return None
        # Apenas recompensas confiáveis concedidas pelo próprio bot geram XP.
        # Cada cookie ganho equivale exatamente a 1 XP; perdas/transferências não alteram XP.
        return self.add_xp(nick, amount, reason=f"cookies ganhos pelo bot ({amount}; conversão 1:1)")

    def choose_class(self, nick, choice):
        with self._lock:
            p = self._ensure(nick)
            if not p: return False, "profile", None
            level = int(p.get("level", 1))
            stage = "provisional" if level <= 9 else "definitive"
            options = (
                p.get("definitive_class_options") or []
                if stage == "definitive"
                else (p.get("class_options") or [])
            )
            if not options or (stage == "provisional" and p.get("class_options_stage") != stage):
                return False, "options", dict(p)
            if p.get("class_name") and not p.get("class_provisional"):
                return False, "chosen", dict(p)
            try: index = int(choice) - 1
            except (TypeError, ValueError): return False, "choice", dict(p)
            if index not in range(len(options)): return False, "choice", dict(p)
            selected = options[index]
            p.update(
                class_name=selected["name"],
                class_description=selected["description"],
                class_options=[],
                class_options_stage=None,
                definitive_class_options=[],
                definitive_class_options_ready=False,
                class_stage=stage,
                class_provisional=(stage == "provisional"),
                lore=None,
                evolved=False,
            )
            p.pop("evolved_class_name", None)
            p.pop("evolved_description", None)
            if level >= 100:
                p["evolved"] = True
                p["evolved_class_name"] = p["class_name"] + " Ascendente"
                p["evolved_description"] = "Uma forma desperta, mais rara e poderosa do seu arquétipo original."
            self._save()
            return True, "chosen", dict(p)

    def set_lore(self, nick, lore):
        with self._lock:
            p = self._ensure(nick)
            if not p or not p.get("class_name"): return False
            p["lore"] = (lore or "").strip()[:280]
            self._save()
            return True

    def get_profile(self, nick):
        key = self._nick(nick)
        if not key: return None
        with self._lock:
            profile = self._users.get(key)
            return dict(profile) if profile is not None else None

    def get_ranking(self, limit=5):
        try: limit = max(0, int(limit))
        except (TypeError, ValueError): limit = 5
        with self._lock:
            ordered = sorted(
                self._users.items(),
                key=lambda item: (int(item[1].get("level", 1)), int(item[1].get("xp", 0)), item[0]),
                reverse=True,
            )
            return [(nick, dict(profile)) for nick, profile in ordered[:limit]]
