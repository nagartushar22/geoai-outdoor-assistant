"""Publish the prepared GeoAI/Qwen GGUF model repository on Hugging Face.

Uses the locally saved Hugging Face login from ``hf auth login``. It does not
read or print a token, and it stops rather than overwriting an existing repo.
"""

from pathlib import Path

from huggingface_hub import HfApi, get_token
from huggingface_hub.errors import RepositoryNotFoundError


ROOT = Path(__file__).resolve().parent
MODEL_CARD_DIR = ROOT / "huggingface-model"
GGUF_FILE = ROOT.parent.parent / ".tmp" / "model-run" / "Qwen3-1.7B-Q8_0.gguf"
REPO_NAME = "geoai-outdoor-assistant-qwen3-1.7b-gguf"


def main() -> None:
    if not get_token():
        raise SystemExit("No saved Hugging Face login. Run `hf auth login` first.")
    if not GGUF_FILE.is_file():
        raise SystemExit(f"Model file not found: {GGUF_FILE}")
    if not (MODEL_CARD_DIR / "README.md").is_file() or not (MODEL_CARD_DIR / "LICENSE").is_file():
        raise SystemExit(f"Model card or license missing from: {MODEL_CARD_DIR}")

    api = HfApi()
    account = api.whoami()
    repo_id = f"{account['name']}/{REPO_NAME}"

    try:
        api.repo_info(repo_id=repo_id, repo_type="model")
    except RepositoryNotFoundError:
        pass
    else:
        raise SystemExit(
            f"Repository already exists; stopped to avoid overwriting it: https://huggingface.co/{repo_id}"
        )

    repo_url = api.create_repo(repo_id=repo_id, repo_type="model", private=False)
    print(f"Created public model repository: {repo_url}", flush=True)

    api.upload_folder(
        folder_path=str(MODEL_CARD_DIR),
        repo_id=repo_id,
        repo_type="model",
        commit_message="Add model card and Apache-2.0 license",
    )
    print("Uploaded README.md and LICENSE.", flush=True)

    api.upload_file(
        path_or_fileobj=str(GGUF_FILE),
        path_in_repo="Qwen3-1.7B-Q8_0.gguf",
        repo_id=repo_id,
        repo_type="model",
        commit_message="Add Qwen3-1.7B Q8_0 GGUF checkpoint",
    )
    print(f"Model upload complete: https://huggingface.co/{repo_id}", flush=True)


if __name__ == "__main__":
    main()
