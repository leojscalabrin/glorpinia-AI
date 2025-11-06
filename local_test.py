# .\venv\Scripts\activate
import os
import sys
import logging

src_path = os.path.join(os.path.dirname(__file__), 'src')
sys.path.append(src_path)

try:
    from glorpinia_bot.gemini_client import GeminiClient
    from glorpinia_bot.memory_manager import MemoryManager
    from glorpinia_bot.twitch_auth import TwitchAuth
except ImportError as e:
    print(f"Erro de importação: {e}")
    print("Verifique se a pasta 'src' existe e contém os arquivos do bot.")
    sys.exit(1)

def main():
    """
    Inicia um loop de chat local para interagir com o 'cérebro' do bot
    diretamente no terminal.
    """
    
    print("Iniciando o chat local...")
    print("Carregando perfil e cliente Gemini...")

    try:
        # Carrega o Auth para pegar o profile.txt
        auth = TwitchAuth()
        
        # Inicializa o Gemini
        gemini_client = GeminiClient(
            personality_profile=auth.personality_profile
        )
        
        # Inicializa um gerenciador de memória
        memory_mgr = MemoryManager()
        
    except Exception as e:
        print(f"Erro fatal ao inicializar o bot: {e}")
        print("Verifique seu arquivo .env e o glorpinia_profile.txt")
        sys.exit(1)

    print("-" * 30)
    print("Chat com Glorpinia (Local)")
    print("Digite 'sair' ou 'exit' para terminar.")
    print("-" * 30)

    # Inicia o loop de chat
    while True:
        try:
            # Pega a entrada do usuário
            query = input("Você: ")

            if query.lower() in ['sair', 'exit']:
                print("Glorpinia: Bedge")
                break
            
            # (Usamos 'local' e 'user' como placeholders para canal e autor)
            response = gemini_client.get_response(
                query=query,
                channel="local_chat",
                author="user",
                memory_mgr=memory_mgr
            )
            
            # Imprime a resposta
            print(f"Glorpinia: {response}")

        except KeyboardInterrupt:
            # Pega o Ctrl+C
            print("\nGlorpinia: Bedge")
            break
        except Exception as e:
            print(f"[ERRO NO CHAT] {e}")

if __name__ == "__main__":
    main()