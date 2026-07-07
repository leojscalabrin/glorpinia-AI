from typing import Dict, Optional


AUXILIARY_CONTEXT_CHAR_BUDGET = 2_400
TRUNCATION_NOTICE = "\n[...contexto auxiliar truncado por limite de tamanho...]"


def _truncate_to_budget(block: str, budget: int) -> Optional[str]:
    """Return block trimmed to budget, preserving room for a truncation notice."""
    if budget <= 0:
        return None

    stripped_block = block.strip()
    if len(stripped_block) <= budget:
        return stripped_block

    if budget <= len(TRUNCATION_NOTICE):
        return None

    available = budget - len(TRUNCATION_NOTICE)
    truncated = stripped_block[:available].rstrip()
    if not truncated:
        return None

    return f"{truncated}{TRUNCATION_NOTICE}"


def _append_auxiliary_blocks(
    blocks: list[str],
    auxiliary_blocks: list[str],
    char_budget: int = AUXILIARY_CONTEXT_CHAR_BUDGET,
) -> None:
    """Append auxiliary blocks by priority, truncating only lower-priority context."""
    remaining_budget = char_budget

    for block in auxiliary_blocks:
        if not block or not block.strip():
            continue

        budgeted_block = _truncate_to_budget(block, remaining_budget)
        if not budgeted_block:
            break

        blocks.append(budgeted_block)
        remaining_budget -= len(budgeted_block)

        if len(budgeted_block) < len(block.strip()):
            break


def build_context_prompt(
    persona_profile: str,
    mood: Optional[str],
    drama_state: Optional[Dict[str, object]],
    memory_loop: Optional[Dict[str, str]],
    social_memory: Optional[str],
    rag_context: Optional[str],
    chat_message: str,
    mention_context: Optional[Dict[str, object]] = None,
    economy_context: Optional[Dict[str, object]] = None,
) -> str:
    required_blocks = []
    auxiliary_blocks = []

    if persona_profile and persona_profile.strip():
        required_blocks.append(f"[SISTEMA: persona profile]\n{persona_profile.strip()}")

    if mention_context is not None:
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
        required_blocks.append(focus_block)

    if chat_message is not None:
        required_blocks.append(f'Mensagem do usuário: "{chat_message.strip()}"')

    if rag_context and rag_context.strip():
        required_blocks.append(f"[SISTEMA: CONTEXTO AUXILIAR]\n{rag_context.strip()}")

    if mood and mood.strip():
        auxiliary_blocks.append(f"[SISTEMA: mood atual = {mood.strip()}]")

    if drama_state:
        favorite = drama_state.get("favorite_of_the_day")
        enemy = drama_state.get("enemy_of_the_day")
        suspect = drama_state.get("suspect")
        rivalry = drama_state.get("rivals")
        drama_block = (
            "[SISTEMA: estado social do chat]\n"
            f"favorito: {favorite}\n"
            f"inimigo: {enemy}\n"
            f"suspeito: {suspect}"
        )
        if rivalry:
            drama_block += f"\nrivalidades: {rivalry}"
        auxiliary_blocks.append(drama_block)

    if memory_loop and memory_loop.get("topic"):
        auxiliary_blocks.append(f"[SISTEMA: memória recorrente]\n{memory_loop['topic']}")

    if social_memory and social_memory.strip():
        auxiliary_blocks.append(
            "[SISTEMA: memória social curta]\n"
            f"{social_memory.strip()}\n"
            "Use como ajuste de tom; não cite como ficha ou histórico explícito."
        )

    if economy_context is not None:
        balances = economy_context.get("balances") or []
        instruction = (economy_context.get("instruction") or "").strip()
        balance_line = " | ".join(balances) if balances else "(sem dados de saldo)"
        economy_block = (
            "[SISTEMA: CONTEXTO DE ECONOMIA (PRIORIDADE BAIXA)]\n"
            f"Saldos atuais: {balance_line}\n"
            f"{instruction or 'Use saldo apenas quando for relevante para a mensagem.'}"
        )
        auxiliary_blocks.append(economy_block)

    blocks = list(required_blocks)
    _append_auxiliary_blocks(blocks, auxiliary_blocks)

    return "\n\n".join(block for block in blocks if block and block.strip())
