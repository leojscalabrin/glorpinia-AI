from typing import Dict, Optional


def build_context_prompt(
    persona_profile: str,
    mood: Optional[str],
    drama_state: Optional[Dict[str, object]],
    memory_loop: Optional[Dict[str, str]],
    rag_context: Optional[str],
    chat_message: str,
    mention_context: Optional[Dict[str, object]] = None,
) -> str:
    blocks = []

    if persona_profile and persona_profile.strip():
        blocks.append(f"[SISTEMA: persona profile]\n{persona_profile.strip()}")

    if mood:
        blocks.append(f"[SISTEMA: mood atual = {mood}]")

    if drama_state:
        favorite = drama_state.get("favorite_of_the_day")
        enemy = drama_state.get("enemy_of_the_day")
        suspect = drama_state.get("suspect")
        rivalry = ", ".join(drama_state.get("rivalries", [])[-3:])
        drama_block = (
            "[SISTEMA: estado social do chat]\n"
            f"favorito: {favorite}\n"
            f"inimigo: {enemy}\n"
            f"suspeito: {suspect}"
        )
        if rivalry:
            drama_block += f"\nrivalidades: {rivalry}"
        blocks.append(drama_block)

    if memory_loop and memory_loop.get("topic"):
        blocks.append(f"[SISTEMA: memória recorrente]\n{memory_loop['topic']}")

    if mention_context:
        trigger_author = (mention_context.get("trigger_author") or "").strip()
        trigger_message = (mention_context.get("trigger_message") or "").strip()
        explicit_mentions = mention_context.get("explicit_mentions") or []
        mentions_line = ", ".join([f"@{m}" for m in explicit_mentions]) if explicit_mentions else "(nenhuma)"

        focus_block = (
            "[SISTEMA: FOCO DA RESPOSTA DE MENÇÃO]\n"
            f"Você foi mencionada por @{trigger_author}.\n"
            f"Mensagem foco (prioridade máxima): {trigger_message}\n"
            f"Usuários mencionados nesta mensagem: {mentions_line}\n"
            "Responda primeiro ao autor da mensagem foco.\n"
            "Use histórico apenas como apoio; não troque o alvo da resposta por causa do histórico.\n"
            "Só cite outras pessoas quando fizer sentido direto com a mensagem foco."
        )
        blocks.append(focus_block)

    if rag_context and rag_context.strip():
        blocks.append(f"[SISTEMA: CONTEXTO AUXILIAR]\n{rag_context.strip()}")

    if chat_message and chat_message.strip():
        blocks.append(f'Mensagem do usuário: "{chat_message.strip()}"')

    non_empty = [block for block in blocks if block and block.strip()]
    return "\n\n".join(non_empty[:6])
