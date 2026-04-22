#!/usr/bin/env python3
"""PBKDF2 + AES-GCM helpers for metrics dashboard payloads."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from typing import Any, Dict

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "cryptography package is required. Install with: pip install cryptography"
    ) from exc


DEFAULT_ITERATIONS = 210_000
SALT_BYTES = 16
IV_BYTES = 12


def _b64e(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _b64d(data: str) -> bytes:
    return base64.b64decode(data.encode("ascii"))


def _derive_key(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=32)


def encrypt_json(payload: Dict[str, Any], password: str, iterations: int = DEFAULT_ITERATIONS) -> Dict[str, Any]:
    if not password:
        raise ValueError("Password is required for encryption")

    plaintext = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    salt = os.urandom(SALT_BYTES)
    iv = os.urandom(IV_BYTES)
    key = _derive_key(password, salt, iterations)
    ciphertext = AESGCM(key).encrypt(iv, plaintext, None)

    return {
        "v": 1,
        "alg": "PBKDF2-SHA256/AES-256-GCM",
        "iterations": iterations,
        "salt": _b64e(salt),
        "iv": _b64e(iv),
        "ciphertext": _b64e(ciphertext),
    }


def decrypt_json(package: Dict[str, Any], password: str) -> Dict[str, Any]:
    iterations = int(package["iterations"])
    salt = _b64d(package["salt"])
    iv = _b64d(package["iv"])
    ciphertext = _b64d(package["ciphertext"])
    key = _derive_key(password, salt, iterations)
    plaintext = AESGCM(key).decrypt(iv, ciphertext, None)
    return json.loads(plaintext.decode("utf-8"))


def _read_password(args: argparse.Namespace) -> str:
    if args.password:
        return args.password
    if args.password_env:
        value = os.environ.get(args.password_env, "")
        if value:
            return value
    raise SystemExit("Password missing. Use --password or --password-env.")


def _cmd_encrypt(args: argparse.Namespace) -> None:
    password = _read_password(args)
    with open(args.input, "r", encoding="utf-8") as f:
        payload = json.load(f)
    package = encrypt_json(payload, password=password, iterations=args.iterations)
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(package, f, ensure_ascii=False, separators=(",", ":"))


def _cmd_decrypt(args: argparse.Namespace) -> None:
    password = _read_password(args)
    with open(args.input, "r", encoding="utf-8") as f:
        package = json.load(f)
    payload = decrypt_json(package, password=password)
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    enc = sub.add_parser("encrypt", help="Encrypt JSON payload file")
    enc.add_argument("--input", required=True)
    enc.add_argument("--output", required=True)
    enc.add_argument("--password")
    enc.add_argument("--password-env")
    enc.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    enc.set_defaults(func=_cmd_encrypt)

    dec = sub.add_parser("decrypt", help="Decrypt JSON payload file")
    dec.add_argument("--input", required=True)
    dec.add_argument("--output", required=True)
    dec.add_argument("--password")
    dec.add_argument("--password-env")
    dec.set_defaults(func=_cmd_decrypt)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
