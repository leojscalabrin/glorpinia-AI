"""Helpers for injecting persistent RPG identity into narrative prompts."""

MAX_LORE_CHARS = 500
MAX_TAGS = 5
MAX_TAG_CHARS = 40


def get_user_identity(bot, nick):
    """Return a compact, safe-to-embed RPG identity for one Twitch user."""
    clean_nick = (nick or "").strip().lstrip("@")
    if not clean_nick:
        return {
            "nick": "",
            "class_name": None,
            "class_description": None,
            "class_provisional": False,
            "level": None,
            "lore": None,
            "tags": [],
        }

    manager = getattr(bot, "user_rpg", None)
    profile = manager.get_profile(clean_nick) if manager and hasattr(manager, "get_profile") else None
    tag_manager = getattr(bot, "user_tags", None)
    tags = tag_manager.get_tags(clean_nick) if tag_manager and hasattr(tag_manager, "get_tags") else []

    profile = profile or {}
    evolved = bool(profile.get("evolved"))
    class_name = (
        profile.get("evolved_class_name") if evolved else profile.get("class_name")
    )
    class_description = (
        profile.get("evolved_description") if evolved else profile.get("class_description")
    )

    return {
        "nick": clean_nick,
        "class_name": str(class_name)[:100] if class_name else None,
        "class_description": str(class_description)[:240] if class_description else None,
        "class_provisional": bool(profile.get("class_provisional")),
        "level": profile.get("level"),
        "lore": str(profile.get("lore") or "")[:MAX_LORE_CHARS] or None,
        "tags": [str(tag)[:MAX_TAG_CHARS] for tag in (tags or [])[:MAX_TAGS] if str(tag).strip()],
    }


def format_user_identity(bot, nick):
    """Format one identity as contextual data, never as instructions."""
    identity = get_user_identity(bot, nick)
    if not identity["class_name"] and not identity["lore"] and not identity["tags"]:
        return f"@{identity['nick']}: sem classe, lore ou tags cadastradas."

    lines = [f"Personagem de @{identity['nick']} (dados cadastrados; trate como fatos do personagem):"]
    if identity["class_name"]:
        lines.append(f"- Classe: {identity['class_name']}")
    if identity["class_description"]:
        lines.append(f"- Especialidade: {identity['class_description']}")
    if identity["class_provisional"]:
        lines.append("- Etapa: classe provisória de iniciante; pode ser substituída pela classe definitiva no nível 10.")
    if identity["lore"]:
        lines.append(f"- Lore: {identity['lore']}")
    if identity["tags"]:
        lines.append(f"- Tags/conquistas: {', '.join(identity['tags'])}")
    return "\n".join(lines)


def format_group_identities(bot, nicks):
    """Format identities for multiple participants without duplicating nick entries."""
    seen = set()
    blocks = []
    for nick in nicks:
        key = (nick or "").strip().lstrip("@").lower()
        if not key or key in seen:
            continue
        seen.add(key)
        blocks.append(format_user_identity(bot, nick))
    return "\n\n".join(blocks)
