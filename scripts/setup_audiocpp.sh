#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="$ROOT/tools/audio.cpp"
for tool in git cmake c++; do
  command -v "$tool" >/dev/null || { printf 'Missing build tool: %s\n' "$tool" >&2; exit 1; }
done
# CUDA installations need not put nvcc on the login shell's PATH.
CUDA_COMPILER="${CUDACXX:-$(command -v nvcc || true)}"
if [[ -z "$CUDA_COMPILER" && -x /usr/local/cuda/bin/nvcc ]]; then
  CUDA_COMPILER=/usr/local/cuda/bin/nvcc
fi
[[ -x "$CUDA_COMPILER" ]] || { printf 'CUDA compiler not found. Install the CUDA toolkit or set CUDACXX=/path/to/nvcc.\n' >&2; exit 1; }
if [[ ! -d "$SOURCE/.git" ]]; then
  git clone --branch v0.8.2 --depth 1 --recurse-submodules https://github.com/0xShug0/audio.cpp.git "$SOURCE"
fi
CUDA_OPTIONS=()
if [[ -n "${CUDAARCHS:-}" ]]; then CUDA_OPTIONS+=("-DCMAKE_CUDA_ARCHITECTURES=$CUDAARCHS"); fi
cmake -S "$SOURCE" -B "$SOURCE/build" -DENGINE_ENABLE_CUDA=ON -DCMAKE_BUILD_TYPE=Release -DCMAKE_CUDA_COMPILER="$CUDA_COMPILER" "${CUDA_OPTIONS[@]}"
cmake --build "$SOURCE/build" --target audiocpp_cli --parallel "${CMAKE_BUILD_PARALLEL_LEVEL:-4}"
printf 'audio.cpp CLI: %s\n' "$SOURCE/build/bin/audiocpp_cli"
