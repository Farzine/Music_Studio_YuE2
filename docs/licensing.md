# Licensing

Three separate things carry three separate licences. Do not treat them as one.

## Model weights — CC BY-NC 4.0

The current YuE2 checkpoint weights (`m-a-p/YuE2-3B`, `m-a-p/YuE2-Vae`) are
licensed **CC BY-NC 4.0**: non-commercial use, with attribution.

This covers the weights and constrains what you may do with what they produce.
Nothing in this application grants any right beyond that licence. If you intend
to use generated audio commercially, resolve that with the model authors first —
the studio cannot and does not clear it for you.

The licence text is downloaded with the weights and sits in your models
directory as `LICENSE`, alongside `THIRD_PARTY_NOTICES.md`.

## Runtime — Apache-2.0

The YuE2 runtime (`yue2-infer`) and the
[YuE repository](https://github.com/multimodal-art-projection/YuE) are
Apache-2.0.

`packages/core/yue2_studio_core/vendor/abc_tools.py` is copied verbatim from
that repository (`skills/yue2-music/scripts/abc_tools.py`) and used as the
authoritative parser for the two-voice ABC dialect. Its licence is preserved
next to it as `LICENSE-abc_tools.txt` and its provenance is stated in the
package docstring. The file is not modified.

## Application source

This repository's own source is separate from both of the above. Nothing here
redistributes model weights.

## Third-party dependencies

Python dependencies are pinned in `services/api/requirements.txt` and
`services/yue2_worker/requirements.txt`; frontend dependencies in
`apps/web/package.json` with a lock file. Review their licences before
redistributing a built artifact.

## Interaction design

The creation flow, song cards, queue and library follow conventions common to
modern music tools. No proprietary source, asset, brand name or protected visual
design from any such product is used, copied or imitated here.

## Practical rules

* Keep the licence files that ship with the weights.
* Attribute the model when you publish anything made with it.
* Do not describe output as unrestricted or commercially cleared.
* Check every third-party licence before redistribution.

The in-app **About** page states the same, so anyone using the studio sees it
without reading the repository.
