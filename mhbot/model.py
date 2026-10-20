"""Download and serve the language model, configured entirely through environment variables.

    python -m mhbot.model pull     download the model file from Hugging Face
    python -m mhbot.model serve    pull if needed, then start an OpenAI-compatible server
    python -m mhbot.model path     print the local model file path

Variables:
    MHBOT_MODEL_REPO       Hugging Face repo id of a GGUF model (owner/name)
    MHBOT_MODEL_FILE       file inside that repo
    MHBOT_MODEL_REVISION   optional branch, tag or commit
    MHBOT_MODEL_PATH       use a local GGUF file instead of downloading
    HF_TOKEN               token for gated or private repos
    MHBOT_MODELS_DIR       download folder (default ./models)
    MHBOT_N_CTX            context size (default 2048)
    MHBOT_N_THREADS        CPU threads (default: all cores)
    MHBOT_N_GPU_LAYERS     layers offloaded to the GPU, -1 for all (default 0)
    MHBOT_CHAT_FORMAT      llama.cpp chat format; unset to use the template stored in the GGUF
    MHBOT_LLM_HOST / MHBOT_LLM_PORT   bind address (default 127.0.0.1:8081)
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def models_dir():
    return Path(os.environ.get("MHBOT_MODELS_DIR") or ROOT / "models")


def local_path():
    explicit = os.environ.get("MHBOT_MODEL_PATH")
    if explicit:
        return Path(explicit)
    filename = os.environ.get("MHBOT_MODEL_FILE")
    return models_dir() / filename if filename else None


def pull():
    explicit = os.environ.get("MHBOT_MODEL_PATH")
    if explicit:
        if not Path(explicit).is_file():
            raise SystemExit("MHBOT_MODEL_PATH does not exist: %s" % explicit)
        return Path(explicit)
    repo, filename = os.environ.get("MHBOT_MODEL_REPO"), os.environ.get("MHBOT_MODEL_FILE")
    if not repo or not filename:
        raise SystemExit("set MHBOT_MODEL_REPO and MHBOT_MODEL_FILE (or MHBOT_MODEL_PATH)")
    target = models_dir() / filename
    if target.is_file():
        print("already downloaded:", target)
        return target
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        raise SystemExit("huggingface_hub is not installed: pip install -r requirements-llm.txt")
    print("downloading %s/%s" % (repo, filename))
    path = hf_hub_download(repo, filename, revision=os.environ.get("MHBOT_MODEL_REVISION") or None,
                           local_dir=str(models_dir()), token=os.environ.get("HF_TOKEN") or None)
    print("saved:", path)
    return Path(path)


def serve():
    path = pull()
    cmd = [sys.executable, "-m", "llama_cpp.server", "--model", str(path),
           "--host", os.environ.get("MHBOT_LLM_HOST", "127.0.0.1"),
           "--port", os.environ.get("MHBOT_LLM_PORT", "8081"),
           "--n_ctx", os.environ.get("MHBOT_N_CTX", "2048"),
           "--n_threads", os.environ.get("MHBOT_N_THREADS") or str(os.cpu_count() or 2),
           "--n_gpu_layers", os.environ.get("MHBOT_N_GPU_LAYERS", "0")]
    chat_format = os.environ.get("MHBOT_CHAT_FORMAT")
    if chat_format:
        cmd += ["--chat_format", chat_format]
    return subprocess.call(cmd)


def main(argv):
    command = argv[0] if argv else ""
    if command == "pull":
        pull()
        return 0
    if command == "serve":
        return serve()
    if command == "path":
        print(local_path() or "")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
