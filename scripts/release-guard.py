"""Fail-closed public-file allowlist; paired with Trivy secret scanning.

No scanner proves absence of secrets. Scientific raw data is never auto-staged.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {"README.md", "LICENSE", "CITATION.cff", "AGENTS.md", ".gitignore", ".dockerignore", "pyproject.toml", "Dockerfile", "Dockerfile.cuda"}
DIRECTORIES = {"src", "tests", "scripts", "docs", "infrastructure", "kubernetes", "experiments", ".github"}
PATTERNS = [re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"), re.compile(rb"gh[pousr]_[A-Za-z0-9]{30,}"), re.compile(rb"github_pat_[A-Za-z0-9_]{30,}"), re.compile(rb"AKIA[A-Z0-9]{16}"), re.compile(rb"(?i)(?:AccountKey|SharedAccessSignature|client_secret|password)\s*[:=]\s*['\"]?[A-Za-z0-9/+_=.-]{12,}")]
FORBIDDEN = {".pem", ".key", ".log", ".tfstate", ".tfvars", ".safetensors", ".pt", ".pth", ".bin", ".parquet", ".zip", ".tar", ".gz", ".kubeconfig"}


def allowed(path: str) -> bool:
    p = Path(path)
    return path in ALLOWED or p.parts[0] in DIRECTORIES or (p.parts[:2] == ("results", "manifests") and p.suffix == ".json")


def check() -> None:
    paths = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT).decode().split("\0")
    errors = []
    for name in sorted(set(paths) - {""}):
        p = ROOT / name
        if not allowed(name) or p.suffix in FORBIDDEN or p.name.startswith(".env"):
            errors.append(f"disallowed file: {name}")
            continue
        if p.is_symlink():
            errors.append(f"symlink: {name}")
            continue
        if not p.exists():
            continue
        if p.stat().st_size > 1024 * 1024:
            errors.append(f"symlink or oversized file: {name}")
            continue
        data = p.read_bytes()
        if any(pattern.search(data) for pattern in PATTERNS):
            errors.append(f"possible secret in {name}; content withheld")
    if errors:
        raise SystemExit("\n".join(errors))
    print("public file allowlist and credential patterns verified")


if __name__ == "__main__":
    check()
