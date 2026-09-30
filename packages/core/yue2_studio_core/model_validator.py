"""Bounded structural readers and optional SHA verification; never load tensors.

Formats: huggingface/safetensors README and ggml-org/ggml docs/gguf.md.
Unknown encodings need validation by a future reader, not a false success.
"""
from __future__ import annotations

import json
import math
import re
import struct
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from .model_metadata import GGUF_COMPANIONS, ModelMetadata, read_json_object as json_object, unique_json_object as _unique_object
from .models import utcnow
from .store import sha256_file

MAX_HEADER = 100_000_000
DTYPE_BYTES = {"BOOL": 1, "U8": 1, "I8": 1, "I16": 2, "U16": 2, "I32": 4, "U32": 4,
               "I64": 8, "U64": 8, "F16": 2, "BF16": 2, "F32": 4, "F64": 8,
               "F8_E4M3": 1, "F8_E5M2": 1}
# GGML type IDs: (encoding, elements per block, bytes per block).
GGML_BLOCKS = {0: ("F32", 1, 4), 1: ("F16", 1, 2), 2: ("Q4_0", 32, 18),
               3: ("Q4_1", 32, 20), 6: ("Q5_0", 32, 22), 7: ("Q5_1", 32, 24),
               8: ("Q8_0", 32, 34), 9: ("Q8_1", 32, 36), 30: ("BF16", 1, 2)}


class UnsupportedEncoding(ValueError):
    pass


def _ranges(ranges: list[tuple[int, int]], size: int, *, contiguous: bool) -> None:
    end = 0
    for start, stop in sorted(ranges):
        if start < end or stop < start or stop > size or (contiguous and start != end):
            raise ValueError("Tensor data overlaps, has gaps, or extends beyond the file.")
        end = stop
    if contiguous and end != size:
        raise ValueError("Tensor data does not cover the complete file payload.")


def safetensors_metadata(path: Path) -> dict:
    size = path.stat().st_size
    with path.open("rb") as stream:
        prefix = stream.read(8)
        if len(prefix) != 8:
            raise ValueError("Truncated safetensors header.")
        length = struct.unpack("<Q", prefix)[0]
        if not 2 <= length <= min(MAX_HEADER, size - 8):
            raise ValueError("Invalid safetensors header length.")
        header_bytes = stream.read(length)
    if not header_bytes.startswith(b"{"):
        raise ValueError("Invalid safetensors JSON header.")
    header = json.loads(header_bytes, object_pairs_hook=_unique_object)
    if not isinstance(header, dict):
        raise ValueError("Safetensors header must be an object.")
    meta = header.pop("__metadata__", {})
    if not isinstance(meta, dict) or any(not isinstance(value, str) for value in meta.values()):
        raise ValueError("Safetensors metadata must contain strings.")
    ranges, types, elements = [], set(), 0
    for tensor in header.values():
        if not isinstance(tensor, dict):
            raise ValueError("Invalid tensor descriptor.")
        shape, offsets, dtype = tensor.get("shape"), tensor.get("data_offsets"), tensor.get("dtype")
        if not isinstance(shape, list) or len(shape) > 32 or any(type(n) is not int or n < 0 for n in shape):
            raise ValueError("Invalid tensor shape.")
        if not isinstance(offsets, list) or len(offsets) != 2 or any(type(n) is not int or n < 0 for n in offsets):
            raise ValueError("Invalid tensor offsets.")
        if not isinstance(dtype, str) or dtype not in DTYPE_BYTES:
            raise UnsupportedEncoding(f"Safetensors encoding {dtype!r} is not supported by the structural reader.")
        count = math.prod(shape)
        if offsets[1] - offsets[0] != count * DTYPE_BYTES[dtype]:
            raise ValueError("Tensor shape, dtype and byte length disagree.")
        ranges.append(tuple(offsets))
        types.add(dtype)
        elements += count
    if not header:
        raise ValueError("The model contains no tensors.")
    _ranges(ranges, size - 8 - length, contiguous=True)
    return {"precision": next(iter(types)) if len(types) == 1 else "mixed",
            "tensor_element_count": elements}


class _GGUFReader:
    def __init__(self, stream, size: int):
        self.stream, self.size = stream, size

    def read(self, count: int) -> bytes:
        if count < 0 or self.stream.tell() + count > min(self.size, MAX_HEADER):
            raise ValueError("Truncated or oversized GGUF metadata/tensor table.")
        value = self.stream.read(count)
        if len(value) != count:
            raise ValueError("Truncated GGUF file.")
        return value

    def number(self, code: str):
        return struct.unpack("<" + code, self.read(struct.calcsize("<" + code)))[0]

    def string(self, limit: int = MAX_HEADER) -> str:
        length = self.number("Q")
        if length > limit:
            raise ValueError("Oversized GGUF string.")
        return self.read(length).decode("utf-8")

    def value(self, kind: int, depth: int = 0):
        if depth > 4:
            raise ValueError("GGUF metadata arrays are nested too deeply.")
        codes = {0: "B", 1: "b", 2: "H", 3: "h", 4: "I", 5: "i", 6: "f", 7: "B", 10: "Q", 11: "q", 12: "d"}
        if kind in codes:
            result = self.number(codes[kind])
            if kind == 7 and result not in (0, 1):
                raise ValueError("Invalid GGUF boolean.")
            return result
        if kind == 8:
            return self.string()
        if kind == 9:
            subtype, count = self.number("I"), self.number("Q")
            if count > 1_000_000:
                raise ValueError("Too many GGUF array elements.")
            for _ in range(count):
                self.value(subtype, depth + 1)
            return None  # Arrays are checked and discarded; no vocabulary allocation.
        raise ValueError(f"Invalid GGUF metadata value type {kind}.")


def gguf_metadata(path: Path) -> dict:
    size = path.stat().st_size
    with path.open("rb") as stream:
        reader = _GGUFReader(stream, size)
        if reader.read(4) != b"GGUF":
            raise ValueError("Invalid GGUF magic bytes.")
        version = reader.number("I")
        if version not in (2, 3):
            raise UnsupportedEncoding(f"GGUF version {version} needs a different structural reader.")
        count, metadata_count = reader.number("Q"), reader.number("Q")
        if not 0 < count <= 1_000_000 or metadata_count > 1_000_000:
            raise ValueError("Invalid GGUF tensor/metadata count.")
        metadata = {}
        for _ in range(metadata_count):
            key = reader.string(65535)
            if key in metadata or not key.isascii():
                raise ValueError("Duplicate or invalid GGUF metadata key.")
            metadata[key] = reader.value(reader.number("I"))
        alignment = metadata.get("general.alignment", 32)
        if type(alignment) is not int or not 8 <= alignment <= 65536 or alignment % 8:
            raise ValueError("Invalid GGUF alignment.")
        ranges, names, types, elements = [], set(), set(), 0
        for _ in range(count):
            name = reader.string(64)
            dimensions = reader.number("I")
            if not name or name in names or not 1 <= dimensions <= 4:
                raise ValueError("Invalid GGUF tensor name/dimensions.")
            names.add(name)
            shape = [reader.number("Q") for _ in range(dimensions)]
            kind, offset = reader.number("I"), reader.number("Q")
            if kind not in GGML_BLOCKS:
                raise UnsupportedEncoding(f"GGUF tensor encoding {kind} needs a different structural reader.")
            encoding, block, block_bytes = GGML_BLOCKS[kind]
            if any(n == 0 for n in shape) or shape[0] % block or offset % alignment:
                raise ValueError("Invalid GGUF tensor shape/alignment.")
            total = math.prod(shape)
            ranges.append((offset, offset + total // block * block_bytes))
            types.add(encoding)
            elements += total
        data_start = stream.tell() + (-stream.tell() % alignment)
    _ranges(ranges, size - data_start, contiguous=False)
    architecture = metadata.get("general.architecture")
    if not isinstance(architecture, str) or not architecture:
        raise ValueError("GGUF general.architecture is missing or invalid.")
    quantized = sorted(kind for kind in types if kind.startswith("Q"))
    return {"architecture": architecture, "tensor_element_count": elements,
            "family": metadata.get("audiocpp.model_spec.family"),
            "quantization": quantized[0] if len(quantized) == 1 else "mixed" if quantized else None,
            "precision": next(iter(types)) if len(types) == 1 and not quantized else "mixed" if not quantized else None}


class ValidationReport(BaseModel):
    schema_version: Literal[1] = 1
    registry_id: str
    checked_at: str
    validation_status: Literal["not_validated", "validated", "failed"]
    compatibility_status: Literal["supported", "incompatible", "unknown"]
    problem: str | None = None
    facts: dict = Field(default_factory=dict)
    files: list[str] = Field(default_factory=list)
    fingerprint: dict = Field(default_factory=dict)
    checksum_verified: bool = False
    checksums: dict[str, str] = Field(default_factory=dict)


def validation_files(entry: ModelMetadata) -> list[str]:
    return sorted({entry.filename or "model.safetensors", "studio-model.json", "weights_manifest.json",
                   *(GGUF_COMPANIONS if entry.format == "gguf" else ("config.json",))})


def file_fingerprint(root: Path, names: list[str]) -> dict:
    result = {}
    for name in names:
        path = root / name
        if path.is_file():
            stat = path.stat()
            result[name] = [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]
        else:
            result[name] = None
    return result


def validate_installation(entry: ModelMetadata, *, verify_checksum: bool = False) -> ValidationReport:
    root = Path(entry.id)
    names = validation_files(entry)
    before = file_fingerprint(root, names)
    report = ValidationReport(registry_id=entry.registry_id, checked_at=utcnow().isoformat(),
                              validation_status="failed", compatibility_status=entry.compatibility_status,
                              fingerprint=before, files=names)
    try:
        if not entry.files_complete:
            raise ValueError(entry.problem or "Required model files are missing.")
        if entry.format == "gguf":
            facts = gguf_metadata(root / entry.filename)
            vae_facts = gguf_metadata(root / "yue2-vae-f16.gguf")
            config = json_object(root / "sidecars/yue2-model-config.json")
            vae_config = json_object(root / "sidecars/yue2-vae-config.json")
            json_object(root / "sidecars/yue2-generation-config.json")
            main_supported = facts["architecture"] == "yue2" or (
                facts["architecture"] == "audiocpp" and facts.get("family") == "yue2"
            )
            if not main_supported or vae_facts["architecture"] not in {"audiocpp", "yue2vae", "yue2_vae"}:
                report.compatibility_status = "incompatible"
            if config.get("model_type") != "yue2" or vae_config.get("model_type") != "yue2_vae":
                report.compatibility_status = "incompatible"
            if vae_facts["precision"] != "F16":
                report.compatibility_status = "incompatible"
        elif entry.format == "safetensors":
            facts = safetensors_metadata(root / entry.filename)
            config = json_object(root / "config.json")
            facts["architecture"] = config.get("model_type") if isinstance(config.get("model_type"), str) else None
            expected = "yue2" if entry.role == "model" else "yue2_vae"
            if facts["architecture"] != expected or entry.filename != "model.safetensors":
                report.compatibility_status = "incompatible"
        else:
            raise UnsupportedEncoding("This model format has no installed structural reader.")
        count = config.get("parameter_count")
        facts["parameter_count"] = count if type(count) is int and count > 0 else None
        facts.pop("family", None)
        report.facts = facts
        report.validation_status = "validated"
        if report.compatibility_status == "incompatible":
            report.problem = "The architecture, model layout or bundled VAE is incompatible with the current YuE2 adapter."
        if verify_checksum:
            manifest_path = root / "weights_manifest.json"
            expected_files = json_object(manifest_path).get("files", {}) if manifest_path.is_file() else {}
            if not isinstance(expected_files, dict):
                raise ValueError("weights_manifest.json files must be an object.")
            weight_names = [entry.filename, *( ["yue2-vae-f16.gguf"] if entry.format == "gguf" else [])]
            for name in weight_names:
                digest = sha256_file(root / name)
                report.checksums[name] = digest
                expected = expected_files.get(name)
                if expected is not None:
                    if not isinstance(expected, dict) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected.get("sha256") or ""):
                        raise ValueError(f"Invalid expected SHA-256 for {name}.")
                    if expected["sha256"].lower() != digest:
                        raise ValueError(f"Checksum mismatch for {name}; restore or download this file again.")
                    if expected.get("bytes") is not None and expected["bytes"] != (root / name).stat().st_size:
                        raise ValueError(f"Size mismatch for {name}.")
            report.checksum_verified = all(name in expected_files for name in weight_names)
            report.facts["checksum_sha256"] = report.checksums[entry.filename]
    except UnsupportedEncoding as exc:
        report.validation_status, report.compatibility_status, report.problem = "not_validated", "unknown", str(exc)
    except (OSError, ValueError, TypeError, KeyError, RecursionError, struct.error) as exc:
        report.validation_status, report.problem = "failed", str(exc)
    if file_fingerprint(root, names) != before:
        report.validation_status, report.problem = "failed", "Model files changed during validation; retry when the files are stable."
    return report
