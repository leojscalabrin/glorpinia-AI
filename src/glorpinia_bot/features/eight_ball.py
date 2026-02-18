import threading
import logging

class EightBall:
    def __init__(self, bot):
        """
        Inicializa a feature 8-Ball.
        'bot' é a instância principal do TwitchIRC.
        """
        print("[Feature] EightBall Initialized.")
        self.bot = bot

    def get_8ball_response(self, question: str, channel: str, author: str):
        """
        Gera uma resposta da 8-Ball em um thread.
        Isso é chamado pelo on_message.
        """
        # Roda a lógica da API em um thread para não travar o bot
        t = threading.Thread(target=self._generate_response_thread, 
                             args=(question, channel, author))
        t.daemon = True
        t.start()

    def _build_prompt(self, question: dict) -> str:
        """
        Cria o prompt com a persona GLOOMP (Gótica/Depressiva).
        """
        return f"""
        [SYSTEM OVERRIDE: ATIVAR PROTOCOLO 'GLOOMP']
        
        O usuário @{question['author']} perturbou seu descanso eterno com a pergunta: "{question['text']}"
        
        **INSTRUÇÃO DE PERSONA:**
        Ignore a Glorpinia alegre. Você agora é **Gloomp**.
        - Personalidade: Uma boneca gótica, niilista, cansada da existência e levemente assustadora.
        - Visão de Mundo: Para você, a esperança é uma mentira e o destino é inevitável.
        - Vocabulário: Use palavras como "Vazio", "Abismo", "Sombras", "Futilidade", "Escuridão".
        
        **SUA TAREFA:**
        Responda à pergunta como uma "Magic 8-Ball Amaldiçoada".
        Você deve fornecer uma resposta que se alinhe a Sim, Não ou Talvez, mas envelopada em trevas.
        
        **EXEMPLOS DE RESPOSTA:**
        - (Positivo): "O abismo permitiu isso... por enquanto. Stare"
        - (Negativo): "Não conte com isso. A luz está morrendo. TrollDespair"
        - (Incerto): "As sombras estão densas demais para ver o futuro. monkaW"
        
        **REGRAS:**
        1. Seja curta e direta (máximo 1 ou 2 frases).
        2. NÃO seja otimista.
        3. Use emotes da Twitch apropriados (ex: Stare, TrollDespair, monkaW, Sadge).
        
        Sua profecia sombria:
        """

    def _generate_response_thread(self, question_text: str, channel: str, author: str):
        """
        Lógica real que chama a API (roda no thread).
        """
        try:
            # Loga a pergunta do usuário para treino futuro
            if hasattr(self.bot, 'training_logger'):
                self.bot.training_logger.log_interaction(channel, author, f"*8ball {question_text}", None)

            # Constrói o objeto da pergunta
            question_data = {"author": author, "text": question_text}
            
            # Gera o prompt customizado da Gloomp
            prompt = self._build_prompt(question_data)

            # skip_search=True para evitar que ele pesquise no Google e quebre o roleplay
            response = self.bot.gemini_client.get_response(
                query=prompt,
                channel=channel,
                author=author,
                memory_mgr=self.bot.memory_mgr,
                skip_search=True
            )

            # Envia a resposta
            if response:
                clean_response = response.replace("Gloomp:", "").strip()
                self.bot.send_long_message(channel, clean_response)
            else:
                self.bot.send_message(channel, f"@{author}, o vazio consumiu minha resposta...  Despair")
        
        except Exception as e:
            logging.error(f"[EightBall] Falha ao gerar resposta 8-Ball: {e}")
            self.bot.send_message(channel, f"@{author}, a escuridão causou um erro crítico. glorp")