"""Persistent XP and RPG classes for Glorpinia."""
import json, logging, math, os, random, threading, time

from .class_options import fallback_evolution_options

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

ASCENSION_SUFFIX = "Ascendente"
ASCENSION_DESCRIPTION = "Uma forma desperta, mais rara e poderosa do seu arquétipo original."


def current_class_name(profile):
    """Nome da classe atual (a última evolução escolhida ou, sem evoluções, a classe base)."""
    evolutions = (profile or {}).get("evolutions") or []
    if evolutions:
        return evolutions[-1].get("name")
    return (profile or {}).get("class_name")


def current_class_description(profile):
    evolutions = (profile or {}).get("evolutions") or []
    if evolutions:
        return evolutions[-1].get("description")
    return (profile or {}).get("class_description")


def effective_class(profile):
    """(nome, descrição) para exibir. Fonte única: no nível 100 o 'Ascendente' vem da classe atual."""
    name = current_class_name(profile)
    if not name:
        return None, None
    if (profile or {}).get("evolved"):
        return f"{name} {ASCENSION_SUFFIX}", profile.get("evolved_description") or ASCENSION_DESCRIPTION
    return name, current_class_description(profile)


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
    # Evolução de classe: estágio -> nível que a libera. O nível 100 segue automático ("Ascendente").
    EVOLUTION_LEVELS = {1: 40, 2: 70}
    ASCENSION_LEVEL = 100
    # Quantos níveis antes do desbloqueio as opções de evolução começam a ser preparadas.
    EVOLUTION_PREP_AHEAD = max(0, min(10, int(os.getenv("EVOLUTION_PREP_AHEAD", "2"))))

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
            "evolution_stage": 0, "evolutions": [], "evolution_options": [], "lore_history": [],
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
        request = self._options_request_locked(p)
        if request:
            hook = self.class_options_hook
            if hook:
                # O gancho só agenda o trabalho em outra thread; nunca bloqueia o fluxo de XP.
                try: hook(self._nick(nick), p.get("last_channel"))
                except Exception as exc: logging.error("[RPG] Falha no gancho de opções de classe: %s", exc)
            elif request["unlocked"] and old < request["unlock_level"]:
                self._store_fallback_locked(p, request)
        if p["level"] >= self.ASCENSION_LEVEL and p.get("class_name") and not p.get("evolved"):
            self._ascend_locked(p)
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
            if p.get("class_name"): return self._choose_evolution_locked(p, choice)
            try: index = int(choice) - 1
            except (TypeError, ValueError): return False, "choice", dict(p)
            options = p.get("class_options") or []
            if not options: return False, "no_options", dict(p)
            if index not in range(len(options)): return False, "choice", dict(p)
            selected = options[index]
            p.update(class_name=selected["name"], class_description=selected["description"], class_options=[], lore=None)
            p.pop("class_options_source", None)
            if p.get("level", 1) >= self.ASCENSION_LEVEL:
                self._ascend_locked(p)
            self._save()
            return True, "chosen", dict(p)

    def _choose_evolution_locked(self, p, choice):
        """Escolha de evolução (níveis 40 e 70). Mesmo fluxo da classe: *class N."""
        stage = self._next_evolution_stage(p)
        if stage is None: return False, "chosen", dict(p)
        level = int(p.get("level", 1))
        if level < self.EVOLUTION_LEVELS[stage]: return False, "evolution_level", dict(p)
        try: index = int(choice) - 1
        except (TypeError, ValueError): return False, "choice", dict(p)
        options = p.get("evolution_options") or []
        if not options: return False, "no_options", dict(p)
        if index not in range(len(options)): return False, "choice", dict(p)

        selected, previous = options[index], current_class_name(p)
        p.setdefault("evolutions", []).append({
            "stage": stage, "name": selected["name"], "description": selected["description"],
            "level": level, "from": previous,
        })
        p["evolution_stage"] = stage
        p["evolution_options"] = []
        for key in ("evolution_options_source", "evolution_options_stage"): p.pop(key, None)
        # A lore anterior vira histórico; a nova é gerada pelo bot logo em seguida (set_lore).
        if p.get("lore"):
            p.setdefault("lore_history", []).append({"stage": stage - 1, "class_name": previous, "lore": p["lore"]})
        p["lore"] = None
        self._sync_ascension(p)
        self._save()
        logging.info("[RPG][Evolução] estágio %d escolhido: %s -> %s", stage, previous, selected["name"])
        return True, "evolved", dict(p)

    def _next_evolution_stage(self, p):
        if not p.get("class_name"): return None
        stage = int(p.get("evolution_stage", 0)) + 1
        return stage if stage in self.EVOLUTION_LEVELS else None

    def next_evolution_level(self, profile):
        """Nível da próxima evolução da pessoa, ou None se não houver mais evoluções a escolher."""
        stage = self._next_evolution_stage(profile or {})
        return self.EVOLUTION_LEVELS.get(stage)

    def _sync_ascension(self, p):
        if p.get("evolved") and p.get("class_name"):
            p["evolved_class_name"] = effective_class(p)[0]

    def _ascend_locked(self, p):
        p["evolved"] = True
        p["evolved_description"] = ASCENSION_DESCRIPTION
        self._sync_ascension(p)

    def _options_request_locked(self, p):
        """O que a pessoa precisa agora: opções de classe, de evolução, ou nada (None)."""
        level = int(p.get("level", 1))
        if not p.get("class_name"):
            if level >= self.CLASS_PREP_LEVEL and not p.get("class_options"):
                return {"kind": "class", "stage": 0, "unlock_level": self.CLASS_UNLOCK_LEVEL,
                        "unlocked": level >= self.CLASS_UNLOCK_LEVEL}
            return None
        stage = self._next_evolution_stage(p)
        if stage is None or p.get("evolution_options"): return None
        unlock = self.EVOLUTION_LEVELS[stage]
        if level < unlock - self.EVOLUTION_PREP_AHEAD: return None
        return {"kind": "evolution", "stage": stage, "unlock_level": unlock, "unlocked": level >= unlock}

    def get_options_request(self, nick):
        """Dict {kind, stage, unlock_level, unlocked} do que falta preparar para a pessoa, ou None."""
        with self._lock:
            p = self._users.get(self._nick(nick))
            return self._options_request_locked(p) if p else None

    @classmethod
    def _pool_options(cls):
        return [{"name": n, "description": d} for n, d in random.sample(CLASS_POOL, cls.CLASS_OPTION_COUNT)]

    def _store_class_options_locked(self, p, options, source):
        p["class_options"] = options
        p["class_options_source"] = source
        self._save()
        logging.info("[RPG][Classes] opções definidas (fonte=%s): %s", source, [o["name"] for o in options])

    def _store_evolution_options_locked(self, p, stage, options, source):
        p["evolution_options"] = options
        p["evolution_options_source"] = source
        p["evolution_options_stage"] = stage
        self._save()
        logging.info("[RPG][Evolução] opções do estágio %d definidas (fonte=%s): %s", stage, source, [o["name"] for o in options])

    def _store_fallback_locked(self, p, request):
        if request["kind"] == "class":
            self._store_class_options_locked(p, self._pool_options(), "pool")
        else:
            options = fallback_evolution_options(current_class_name(p), request["stage"])
            self._store_evolution_options_locked(p, request["stage"], options, "fallback")

    def set_evolution_options(self, nick, options, source="ai"):
        """Grava as opções de evolução do estágio pendente. Nunca sobrescreve opções existentes."""
        try:
            clean = [{"name": str(o["name"]).strip(), "description": str(o["description"]).strip()} for o in options]
        except (TypeError, KeyError):
            return False
        if len(clean) != self.CLASS_OPTION_COUNT or not all(o["name"] and o["description"] for o in clean):
            return False
        with self._lock:
            p = self._users.get(self._nick(nick))
            request = self._options_request_locked(p) if p else None
            if not request or request["kind"] != "evolution": return False
            self._store_evolution_options_locked(p, request["stage"], clean, source)
            return True

    def assign_fallback_options(self, nick):
        """Reserva para o que estiver pendente (classe ou evolução), só para quem já desbloqueou."""
        with self._lock:
            p = self._users.get(self._nick(nick))
            request = self._options_request_locked(p) if p else None
            if not request or not request["unlocked"]: return False
            self._store_fallback_locked(p, request)
            return True

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
