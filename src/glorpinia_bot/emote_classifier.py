import re
from collections import defaultdict

_TOKEN_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z0-9]+|[A-Z]+")


def tokenize_emote_name(name: str):
    return [t.lower() for t in _TOKEN_RE.findall(name) if t]


ROOT_EMOTION_MAP = {
    # laugh
    "kek": "laugh", "kekw": "laugh", "lul": "laugh",
    "lol": "laugh", "haha": "laugh", "omegalul": "laugh", "xd": "laugh",
    "laugh": "laugh", "laughing": "laugh", "funny": "laugh",
    # hype
    "pog": "hype", "poggers": "hype", "pogu": "hype", "pogchamp": "hype",
    "hype": "hype", "letsgo": "hype", "lesgo": "hype", "poggies": "hype",
    "hyped": "hype",
    # happy
    "happy": "happy", "yay": "happy", "glad": "happy", "smile": "happy",
    "smiling": "happy", "joy": "happy",
    # sad
    "sad": "sad", "sadge": "sad", "cry": "sad", "crying": "sad",
    "despair": "sad", "unhappy": "sad", "hands": "sad",  # "PepeHands"
    # mockery
    "kappa": "mockery", "troll": "mockery", "trolling": "mockery",
    "smug": "mockery", "smirk": "mockery",
    # scared / panic
    "monka": "scared", "scared": "scared", "fear": "scared", "nervous": "scared",
    "panic": "panic", "panik": "panic", "help": "panic", "scream": "panic",
    # angry / rage
    "angry": "angry", "mad": "angry", "triggered": "angry", "furious": "angry",
    "rage": "rage", "tilt": "rage", "tilted": "rage",
    # shock
    "shock": "shock", "shocked": "shock", "surprised": "shock", "wtf": "shock",
    "omg": "shock", "gasp": "shock", "nani": "shock",
    # cute
    "cute": "cute", "aww": "cute", "uwu": "cute", "wholesome": "cute",
    # suspicion
    "sus": "suspicion", "suspicious": "suspicion", "suspect": "suspicion",
    "sussy": "suspicion",
    # superiority / denial / approval
    "ez": "superiority", "easy": "superiority", "chad": "superiority",
    "cope": "denial", "copium": "denial", "seethe": "denial", "denied": "denial",
    "based": "approval", "nodders": "approval", "nod": "approval", "yes": "approval",
    "approved": "approval",
    # clap / congratulation
    "clap": "clap", "gg": "congratulation", "win": "congratulation",
    "win2": "congratulation", "victory": "congratulation", "ggs": "congratulation",
    # dumb / smart
    "dumb": "dumb", "stupid": "dumb", "smoothbrain": "dumb",
    "smart": "smart", "galaxybrain": "smart", "iq": "smart",
    # sleep / tired
    "sleep": "sleep", "sleepy": "sleep", "zzz": "sleep", "yawn": "sleep",
    "tired": "tired", "exhausted": "tired",
    # eating
    "eat": "eating", "eating": "eating", "nom": "eating", "chew": "eating",
    "hungry": "eating", "food": "eating",
    # dancing / running
    "dance": "dancing", "dancing": "dancing", "boogie": "dancing",
    "run": "running", "running": "running", "zoom": "running", "fast": "running",
    # greeting / farewell
    "hi": "greeting", "hello": "greeting", "wave": "greeting", "welcome": "greeting",
    "bye": "farewell", "goodbye": "farewell", "leave": "farewell",
    # thinking / relaxing / relief / hope / praying
    "think": "thinking", "thinking": "thinking", "hmm": "thinking",
    "chill": "relaxing", "relax": "relaxing", "relaxed": "relaxing",
    "phew": "relief", "relief": "relief",
    "hope": "hope", "hopium": "hope",
    "pray": "praying", "praying": "praying", "amen": "praying",
    # peak / cringe / clown / evil / elegant / stare / bald
    "peak": "peak", "cringe": "cringe", "clown": "clown", "circus": "clown",
    "evil": "evil", "devil": "evil", "elegant": "elegant", "fancy": "elegant",
    "stare": "stare", "staring": "stare", "bald": "bald",
    # gambling / business / fight / magic
    "gamba": "gambling", "casino": "gambling", "bet": "gambling",
    "business": "business", "office": "business",
    "fight": "fight", "punch": "fight", "battle": "fight",
    "magic": "magic", "wizard": "magic",
}

WHOLE_NAME_OVERRIDES = {
    "kappa": "mockery",
    "kekw": "laugh",
    "omegalul": "laugh",
    "pog": "hype",
    "poggers": "hype",
    "pogchamp": "hype",
    "sadge": "sad",
    "feelsbadman": "sad",
    "feelsgoodman": "happy",
    "monkas": "scared",
    "monkaw": "panic",
    "ez": "superiority",
    "clap": "clap",
    "nodders": "approval",
    "copium": "denial",
    "hopium": "hope",
    "pepehands": "sad",
    "widepeepohappy": "happy",
    "widepeeposad": "sad",
}


def classify_emote_name(name: str):
    """
    Tenta inferir a emoção/intenção de um emote a partir do nome.
    Retorna a categoria (ex.: 'happy', 'laugh') ou None se não conseguir
    adivinhar com confiança -> nesse caso o emote fica só no pool 'neutral'.
    """
    lowered = re.sub(r"[^a-z0-9]", "", name.lower())

    if lowered in WHOLE_NAME_OVERRIDES:
        return WHOLE_NAME_OVERRIDES[lowered]

    tokens = tokenize_emote_name(name)
    score = defaultdict(int)

    for token in tokens:
        emotion = ROOT_EMOTION_MAP.get(token)
        if emotion:
            score[emotion] += 2

    if not score:
        for root, emotion in ROOT_EMOTION_MAP.items():
            if len(root) >= 4 and root in lowered:
                score[emotion] += 1

    if not score:
        return None

    return max(score.items(), key=lambda kv: kv[1])[0]