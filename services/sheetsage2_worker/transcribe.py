#!/usr/bin/env python
"""SheetSage2 transcription, run in its own environment.

SheetSage2 pins torch 2.8.0 and transformers 4.45.2; YuE2 pins 2.10.0 and
4.57.6. They cannot share an interpreter, so this runs as a separate process in
.venv-sheetsage2 and exchanges files and one JSON document with the caller.

    python -m services.sheetsage2_worker.transcribe \
        --audio reference.wav --output cover-score --model models/SheetSage2 \
        --report report.json

The report always exists, including on failure, so the caller never has to
parse stderr to find out what happened.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path


def write_report(path: Path | None, payload: dict) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", required=True, help="Local SheetSage2 directory or repo id")
    parser.add_argument("--report", type=Path, help="Where to write the JSON report")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--dtype", choices=("bf16", "fp32"), default="bf16")
    parser.add_argument("--max-seconds", type=float, default=None)
    parser.add_argument(
        "--with-chords",
        action="store_true",
        help="Keep chord symbols. The default is melody only, which is what a cover needs.",
    )
    parser.add_argument("--local-files-only", action="store_true")
    args = parser.parse_args()

    started = time.monotonic()
    report: dict = {"status": "failed", "audio": str(args.audio), "output": str(args.output)}

    try:
        if not args.audio.is_file():
            raise FileNotFoundError(f"reference audio not found: {args.audio}")

        import torch
        from transformers import AutoModel

        torch.set_num_threads(min(4, torch.get_num_threads()))
        device = args.device
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"

        model = (
            AutoModel.from_pretrained(
                args.model, local_files_only=args.local_files_only, trust_remote_code=True
            )
            .eval()
            .to(device)
        )

        options: dict = {"dtype": args.dtype, "melody_only": not args.with_chords}
        if args.max_seconds is not None:
            options["max_seconds"] = args.max_seconds

        result = model.transcribe(args.audio, output_dir=args.output, **options)

        abc = result.get("abc")
        if not abc or result.get("abc_error"):
            raise RuntimeError(
                result.get("abc_error") or "SheetSage2 produced no ABC score for this recording"
            )

        score_path = Path(args.output) / "score.abc"
        report.update(
            {
                "status": "complete",
                "abc": abc,
                "score_path": str(score_path) if score_path.is_file() else None,
                "warnings": list(result.get("warnings") or []),
                "duration_seconds": result.get("duration_seconds"),
                "melody_only": not args.with_chords,
                "device": device,
                "elapsed_seconds": round(time.monotonic() - started, 2),
            }
        )
        write_report(args.report, report)
        print(json.dumps({k: v for k, v in report.items() if k != "abc"}, ensure_ascii=False))
        return 0

    except BaseException as exc:  # noqa: BLE001 - every failure is reported
        report.update(
            {
                "status": "failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(limit=6),
                "elapsed_seconds": round(time.monotonic() - started, 2),
            }
        )
        write_report(args.report, report)
        print(json.dumps({k: v for k, v in report.items() if k != "traceback"}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
