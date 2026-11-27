import asyncio
import hashlib
from concurrent.futures.thread import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

_HASH_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="turbofetch-hash")

SUPPORTED_ALGORITHMS: dict[str, Callable] = {
    "md5": hashlib.md5,
    "sha1": hashlib.sha1,
    "sha256": hashlib.sha256,
}

CHUNK_SIZE: int = 131072


def _compute_hash(file_path: Path, algorithm: str) -> str:
    hash_func = SUPPORTED_ALGORITHMS[algorithm]()
    with open(file_path, "rb") as f:
        while chunk := f.read(CHUNK_SIZE):
            hash_func.update(chunk)
    return hash_func.hexdigest()


async def verify_checksum(
    file_path: Path, expected: str, algorithm: str = "sha256"
) -> bool:
    if algorithm not in SUPPORTED_ALGORITHMS:
        raise ValueError(f"Unsupported algorithm: {algorithm}")
    loop = asyncio.get_running_loop()
    computed = await loop.run_in_executor(_HASH_EXECUTOR, _compute_hash, file_path, algorithm)
    return computed.lower() == expected.lower()
