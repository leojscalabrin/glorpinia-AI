"""Lightweight package init: avoid importing heavy runtime modules here.

Import submodules explicitly where needed, e.g.:
    from glorpinia_bot.hf_client import HFClient

This prevents `import glorpinia_bot` from executing network or audio deps.
"""

# Export names for convenience but do NOT import modules here to avoid side-effects.
__all__ = [
    'TwitchIRC',
    'TwitchAuth',
    'HFClient',
    'MemoryManager'
]