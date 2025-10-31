"""Lightweight package init: avoid importing heavy runtime modules here.

This prevents `import glorpinia_bot` from executing network or audio deps.
"""

# Export names for convenience but do NOT import modules here to avoid side-effects.
__all__ = [
    'TwitchIRC',
    'TwitchAuth',
    'GeminiClient', 
    'MemoryManager'
]