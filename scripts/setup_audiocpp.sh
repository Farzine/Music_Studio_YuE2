#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="$ROOT/tools/audio.cpp"
if [[ ! -d "$SOURCE/.git" ]]; then
  git clone --branch v0.8.2 --depth 1 --recurse-submodules https://github.com/0xShug0/audio.cpp.git "$SOURCE"
fi
cmake -S "$SOURCE" -B "$SOURCE/build" -DENGINE_ENABLE_CUDA=ON -DCMAKE_BUILD_TYPE=Release
cmake --build "$SOURCE/build" --target audiocpp_cli --parallel "$(nproc)"
printf 'audio.cpp CLI: %s\n' "$SOURCE/build/bin/audiocpp_cli"
