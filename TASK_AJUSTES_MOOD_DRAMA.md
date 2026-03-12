# Tarefa: Ajustes de Mood, Emotes, Drama Engine e Segurança de Mensagens

## Objetivo
Ajustar o pipeline de mensagens para que o comportamento emocional e social da bot fique mais contextual, com gatilhos aleatórios realmente passivos e sem efeitos colaterais de cookies/emotes fora da resposta principal.

## Escopo implementado

- [x] **Mood contextual (não só palavra-chave):**
  - Inferência de mood agora considera se a mensagem está direcionada à bot (menção/segunda pessoa) e o tom da frase.
  - Rudeza direcionada aumenta chance de `angry`; elogio direcionado pode gerar `happy`; pergunta contextual à bot pode gerar `curious`.

- [x] **Remover peso do mood na escolha de emote:**
  - `EmoteManager` agora resolve emoção apenas pelo contexto textual da própria mensagem final.
  - `mood` foi mantido apenas na assinatura por compatibilidade, sem alterar escolha de emote.

- [x] **Drama engine influenciando mensagens + gatilhos por mensagem lida:**
  - `observe_message` continua rodando para toda mensagem de chat lida (não só menção ao bot).
  - Novo gatilho passivo de **imposto imperial** com probabilidade aleatória e cooldown por canal, acionado no fluxo de leitura de mensagens.
  - Mensagem do imposto usa injeção de contexto social (`mood`, `drama_state`, `memory_loop`) para influenciar a saída.

- [x] **Cookies e emotes apenas na criação da mensagem principal (menção):**
  - Execução de ações de cookie via IA agora é explícita por chamada (`allow_cookie_actions=True`) e usada no fluxo principal de menção.
  - Comentários proativos e outros fluxos de sistema não processam mais comandos de cookie automáticos.
  - Comentários proativos não passam mais pelo `prepare_final_bot_message` (sem auto-emote nesse fluxo).

- [x] **Segurança contra comando de cookie no meio de glitch/texto:**
  - `CookieSystem` passou a aceitar/executar tags `COOKIE` apenas quando estão em **bloco final da mensagem**.
  - Tags no meio do texto (ex.: trecho de glitch) são ignoradas para transação.

## Critérios de validação

- [ ] Mensagens rudes direcionadas à bot alteram mood com mais consistência.
- [ ] Emote final muda pelo contexto do texto final, não pelo mood injetado.
- [ ] Imposto imperial dispara passivamente (sem menção) ao longo do chat, respeitando cooldown.
- [ ] Comentários proativos não executam transações de cookie e não recebem emote automático do `EmoteManager`.
- [ ] Tags de cookie fora do fim da mensagem não executam transação.

