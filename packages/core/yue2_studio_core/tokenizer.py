"""The checkpoint's own text tokenizer, for exact context accounting.

Token budgets are only meaningful if they are counted the way the model counts
them, so this reproduces ``yue2.tokenization_yue2.YuE2TextTokenizer`` exactly:
the same ``qwen.tiktoken`` merge file, the same split pattern, the same NFC
normalisation. It is duplicated rather than imported because the API process
deliberately has no torch and therefore cannot import the runtime package.

If the merge file or ``tiktoken`` is unavailable the caller still gets a count,
clearly marked inexact, rather than nothing at all.
"""
from __future__ import annotations

import base64
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

#: Ordinary (non-special) tokens in the checkpoint-native merge file.
ORDINARY_TOKENS = 151643

_PATTERN = (
    r"(?i:'s|'t|'re|'ve|'m|'ll|'d)|[^\r\n\p{L}\p{N}]?\p{L}+|\p{N}|"
    r" ?[^\s\p{L}\p{N}]+[\r\n]*|\s*[\r\n]+|\s+(?!\S)|\s+"
)

#: Bytes per token observed for English prose with this BPE. Used only when the
#: real tokenizer cannot be loaded, and every result says so.
FALLBACK_BYTES_PER_TOKEN = 3.6


@dataclass(frozen=True)
class TokenCount:
    tokens: int
    exact: bool
    reason: str | None = None


class TextTokenizer:
    """Wraps the checkpoint merge file; ``exact`` is False when it is missing."""

    def __init__(self, merge_file: Path | None) -> None:
        self.merge_file = merge_file
        self._encoding = None
        self._reason: str | None = None
        if merge_file is None or not Path(merge_file).is_file():
            self._reason = f"qwen.tiktoken not found at {merge_file}"
            return
        try:
            import tiktoken
        except ImportError:
            self._reason = "tiktoken is not installed in this process"
            return
        try:
            ranks = {
                base64.b64decode(token): int(rank)
                for token, rank in (
                    line.split() for line in Path(merge_file).read_bytes().splitlines() if line
                )
            }
            if len(ranks) != ORDINARY_TOKENS:
                raise ValueError(
                    f"expected {ORDINARY_TOKENS} ordinary tokens, found {len(ranks)}"
                )
            specials = ["<|endoftext|>", "<|im_start|>", "<|im_end|>", "<R>", "<S>", "<X>", "<mask>", "<sep>"]
            specials += [f"<extra_{index}>" for index in range(200)]
            specials[204:206] = ["<abc>", "</abc>"]
            self._encoding = tiktoken.Encoding(
                "YuE2",
                pat_str=_PATTERN,
                mergeable_ranks=ranks,
                special_tokens={name: index + len(ranks) for index, name in enumerate(specials)},
            )
        except Exception as exc:  # a broken merge file must not break estimation
            self._reason = f"could not load the tokenizer: {exc}"

    @property
    def exact(self) -> bool:
        return self._encoding is not None

    def count(self, text: str) -> TokenCount:
        if not text:
            return TokenCount(0, self.exact, self._reason)
        if self._encoding is not None:
            return TokenCount(len(self._encoding.encode_ordinary(unicodedata.normalize("NFC", text))), True)
        estimate = int(len(text.encode("utf-8")) / FALLBACK_BYTES_PER_TOKEN) + 1
        return TokenCount(estimate, False, self._reason)


@lru_cache(maxsize=4)
def get_tokenizer(merge_file: str | None) -> TextTokenizer:
    return TextTokenizer(Path(merge_file) if merge_file else None)
