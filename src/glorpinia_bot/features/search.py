import os
import logging
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()

class SearchTool:
    def __init__(self):
        """
        Inicializa a ferramenta de busca da Google API.
        """
        self.api_key = os.getenv("GOOGLE_SEARCH_API_KEY")
        self.pse_id = os.getenv("PROGRAMMABLE_SEARCH_ENGINE_ID")
        
        if not self.api_key or not self.pse_id:
            logging.warning("[SearchTool] GOOGLE_SEARCH_API_KEY ou PROGRAMMABLE_SEARCH_ENGINE_ID não encontrados no .env. A busca será desativada.")
            self.service = None
        else:
            try:
                self.service = build("customsearch", "v1", developerKey=self.api_key)
                print("[Feature] SearchTool Initialized.")
            except Exception as e:
                logging.error(f"[SearchTool] Falha ao inicializar o serviço de busca: {e}")
                self.service = None

    def perform_search(self, query: str, num_results=3) -> str | None:
        """
        Executa uma busca na web e retorna os snippets formatados.
        Retorna None se a busca falhar ou for desnecessária.
        """
        if not self.service:
            return None # Ferramenta não inicializada

        try:
            logging.info(f"[SearchTool] Buscando na web por: {query}")
            
            # Executa a chamada da API
            result = self.service.cse().list(
                q=query,
                cx=self.pse_id,
                num=num_results
            ).execute()

            # Formata os resultados
            items = result.get('items')
            if not items:
                logging.info(f"[SearchTool] Nenhuma resultado encontrado para: {query}")
                return None
            
            snippets = []
            for i, item in enumerate(items):
                snippets.append(f"Fonte {i+1} ({item.get('title')}): {item.get('snippet')}")
            
            # Retorna um único bloco de texto de contexto
            return "\n".join(snippets)

        except Exception as e:
            logging.error(f"[SearchTool] Erro ao buscar na API: {e}")
            return None