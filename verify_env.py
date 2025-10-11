"""
verify_env.py
Simple script to check that required packages import successfully and print recommendations.
Run inside your virtualenv to verify environment.
"""
import importlib
import sys

checks = [
    "dotenv",
    "requests",
    "websocket",
    "langchain",
    "langchain_core",
    "langchain_huggingface",
    "langchain_community",
    "transformers",
    "peft",
    # bitsandbytes is optional on Windows and often GPU/CUDA-specific
    "bitsandbytes",
    # FAISS is usually importable as `faiss` when faiss-cpu is installed
    "faiss",
    "streamlink",
    "pydub",
    "whisper",
]

results = {}
for mod in checks:
    try:
        importlib.import_module(mod)
        results[mod] = (True, None)
    except Exception as e:
        results[mod] = (False, str(e))

print("Environment verification results:\n")
for mod, (ok, err) in results.items():
    if ok:
        print(f"OK: {mod}")
    else:
        print(f"MISSING or ERROR: {mod} -> {err}")

# Summarize
missing = [m for m,(ok,_) in results.items() if not ok]
if missing:
    print("\nMissing or failing modules detected:")
    for m in missing:
        # Provide additional hints for common optional/OS-specific modules
        if m == 'bitsandbytes':
            print(f" - {m} (optional on Windows; install only if you have a compatible CUDA + want quantization)")
        elif m == 'faiss':
            print(f" - {m} (if you installed faiss-cpu, try `python -c \"import faiss; print(faiss.__version__)\"` to verify)")
        else:
            print(f" - {m}")
    print("\nRecommendation: activate the virtualenv and run:\n    python -m pip install -r requirements.txt\nOr if you have GPU and need quantization, use requirements-gpu.txt and install torch for your CUDA version as described in README.")
    sys.exit(2)
else:
    print("\nAll checked modules import successfully. Environment looks good.")
    sys.exit(0)
