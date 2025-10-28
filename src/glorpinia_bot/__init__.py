"""Lightweight package init: avoid importing heavy runtime modules here.

Import submodules explicitly where needed, e.g.:
    from glorpinia_bot.ollama_client import OllamaClient

This prevents `import glorpinia_bot` from executing network or audio deps.
"""

# Export names for convenience but do NOT import modules here to avoid side-effects.
__all__ = [
    'TwitchIRC',
    'TwitchAuth',
    'OllamaClient', 
    'MemoryManager'
]