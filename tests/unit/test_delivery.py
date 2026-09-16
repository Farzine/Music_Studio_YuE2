"""Download delivery: format support and filename safety.

Nothing here converts anything. These cover the two places a download can go
wrong quietly: offering a format this machine cannot produce, and letting a
typed filename escape the download it belongs to.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from yue2_studio_core.delivery import (
    FORMATS,
    FORMATS_BY_ID,
    available_encoders,
    format_catalogue,
    sanitise_download_name,
    source_format_id,
    sweep_temporary,
)


# -- the catalogue ---------------------------------------------------------- #


def test_every_format_is_listed_with_the_encoder_it_needs():
    for item in FORMATS:
        assert item.extension.startswith(".")
        assert item.mime
        assert item.encoder
        assert item.arguments, f"{item.id} has no ffmpeg arguments"


def test_a_missing_ffmpeg_leaves_only_the_source_format_available():
    catalogue = format_catalogue(ffmpeg=None, source=Path("final.flac"))
    by_id = {entry["id"]: entry for entry in catalogue}
    # The master itself can always be handed over: no conversion is involved.
    assert by_id["flac"]["supported"] is True
    assert by_id["flac"]["is_source"] is True
    assert by_id["mp3"]["supported"] is False
    assert "FFmpeg" in by_id["mp3"]["reason"]


def test_an_unsupported_format_says_why_rather_than_disappearing():
    catalogue = format_catalogue(ffmpeg=None)
    assert len(catalogue) == len(FORMATS)
    for entry in catalogue:
        assert entry["supported"] or entry["reason"]


def test_the_bundled_ffmpeg_supports_every_advertised_format():
    """The formats offered are the ones this repository's FFmpeg can write."""
    from yue2_studio_core.settings import get_settings

    ffmpeg = get_settings().ffmpeg_path
    if not ffmpeg.is_file():
        pytest.skip("FFmpeg is not installed; run scripts/setup_cover.sh")
    encoders = available_encoders(ffmpeg)
    assert encoders, "ffmpeg -encoders reported nothing"
    missing = [item.id for item in FORMATS if item.encoder not in encoders]
    assert missing == [], f"these formats would be offered but could not be written: {missing}"


def test_source_format_is_recognised_from_the_extension():
    assert source_format_id("audio/final.flac") == "flac"
    assert source_format_id(Path("final.WAV")) == "wav"
    assert source_format_id("final.aiff") is None


# -- filenames -------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("My Awesome Song", "My Awesome Song.mp3"),
        # The user typed the extension already: it is not repeated.
        ("My Awesome Song.mp3", "My Awesome Song.mp3"),
        # A different audio extension is replaced, not stacked.
        ("My Awesome Song.flac", "My Awesome Song.mp3"),
        # Anything that looks like a path becomes a plain name.
        ("../../etc/passwd", "passwd.mp3"),
        ("/absolute/path/song", "song.mp3"),
        ("..\\..\\windows\\system32", "system32.mp3"),
        # Characters a filesystem or a header could misread.
        ('quote"colon:star*', "quotecolonstar.mp3"),
        # Nothing usable left: the fallback is used.
        ("", "fallback-name.mp3"),
        ("   ", "fallback-name.mp3"),
        ("...", "fallback-name.mp3"),
        ("///", "fallback-name.mp3"),
        # Reserved on Windows, so it would fail to save there.
        ("CON", "CON-audio.mp3"),
        # A version number is not an extension.
        ("Mix v1.2", "Mix v1.2.mp3"),
    ],
)
def test_a_typed_filename_is_made_safe(typed, expected):
    assert sanitise_download_name(typed, fallback="fallback-name", extension=".mp3") == expected


def test_newlines_and_control_characters_are_removed():
    typed = "line" + chr(10) + "break" + chr(0) + chr(127)
    assert sanitise_download_name(typed, fallback="song", extension=".mp3") == "line break.mp3"


def test_a_filename_never_contains_a_separator_whatever_is_typed():
    for typed in ["a/b", "a" + chr(92) + "b", "a//..//b", chr(0) + "null", ".."]:
        result = sanitise_download_name(typed, fallback="song", extension=".wav")
        assert "/" not in result and chr(92) not in result
        assert not result.startswith(".")
        assert result.endswith(".wav")


def test_a_very_long_filename_is_capped_but_keeps_its_extension():
    result = sanitise_download_name("x" * 500, fallback="song", extension=".flac")
    assert result.endswith(".flac")
    assert len(result) <= 126


def test_every_format_appends_its_own_extension():
    for item in FORMATS:
        assert sanitise_download_name("song", fallback="s", extension=item.extension) == f"song{item.extension}"
        # And asking for the same format twice never doubles it.
        assert (
            sanitise_download_name(f"song{item.extension}", fallback="s", extension=item.extension)
            == f"song{item.extension}"
        )


def test_an_unknown_format_id_is_not_in_the_catalogue():
    assert "aiff" not in FORMATS_BY_ID


# -- temporary files -------------------------------------------------------- #


def test_the_sweep_removes_only_files_past_their_time(tmp_path: Path):
    import os
    import time

    fresh = tmp_path / "fresh.mp3"
    stale = tmp_path / "stale.mp3"
    fresh.write_bytes(b"x")
    stale.write_bytes(b"x")
    old = time.time() - 3600
    os.utime(stale, (old, old))

    assert sweep_temporary(tmp_path, ttl_seconds=900) == 1
    assert fresh.is_file()
    assert not stale.exists()


def test_the_sweep_on_a_missing_directory_is_not_an_error(tmp_path: Path):
    assert sweep_temporary(tmp_path / "nothing-here") == 0
