from typing import Dict, Optional


def build_context_prompt(
    persona_profile: str,
    mood: Optional[str],
    drama_state: Optional[Dict[str, object]],
    memory_loop: Optional[Dict[str, str]],
    rag_context: Optional[str],
    chat_message: str,
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

    if rag_context and rag_context.strip():
        blocks.append(rag_context.strip())

    if chat_message and chat_message.strip():
        blocks.append(f'Mensagem do usuário: "{chat_message.strip()}"')

    non_empty = [block for block in blocks if block and block.strip()]
    return "\n\n".join(non_empty[:6])
