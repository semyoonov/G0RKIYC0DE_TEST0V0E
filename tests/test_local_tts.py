from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.exceptions import ConfigurationError, SpeechSynthesisError
from app.ai.tts.local_tts import LocalTextToSpeech

WAV_BYTES = b"RIFF$\x00\x00\x00WAVEfmt "


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "database_url": "sqlite+aiosqlite://",
        "cache_enabled": False,
        "auto_create_tables": False,
        "sber_tts_credentials": "",
        "local_tts_enabled": True,
        "local_tts_binary": "espeak-ng",
        "local_tts_voice": "ru",
        "local_tts_speed": 150,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def fake_espeak(path: Path) -> Path:
    script = path / "espeak-ng"
    script.write_text(
        "#!/bin/sh\n"
        'out=""\n'
        'while [ "$#" -gt 0 ]; do\n'
        '  if [ "$1" = "-w" ]; then out="$2"; shift 2; continue; fi\n'
        "  shift\n"
        "done\n"
        f'printf "%s" "{WAV_BYTES.decode("latin-1")}" > "$out"\n',
        encoding="latin-1",
    )
    script.chmod(0o755)
    return script


def fake_ffmpeg(path: Path) -> Path:
    script = path / "ffmpeg"
    script.write_text(
        "#!/bin/sh\n"
        'src=""\n'
        'dst=""\n'
        'previous=""\n'
        'for arg in "$@"; do\n'
        '  if [ "$previous" = "-i" ] || [ -n "$dst" ]; then :; fi\n'
        '  if [ "$previous" = "-i" ]; then src="$arg"; fi\n'
        '  dst="$arg"\n'
        '  previous="$arg"\n'
        "done\n"
        'printf "OGGOPUS" > "$dst"\n',
    )
    script.chmod(0o755)
    return script


async def test_synthesize_returns_opus_container(tmp_path: Path) -> None:
    fake_espeak(tmp_path)
    fake_ffmpeg(tmp_path)
    tts = LocalTextToSpeech(make_settings(), binary=str(tmp_path / "espeak-ng"), ffmpeg=str(tmp_path / "ffmpeg"))

    audio = await tts.synthesize("Привет, это ассистент", audio_format="opus")

    assert audio == b"OGGOPUS"
    await tts.close()


async def test_synthesize_returns_wav_without_ffmpeg(tmp_path: Path) -> None:
    fake_espeak(tmp_path)
    tts = LocalTextToSpeech(
        make_settings(),
        binary=str(tmp_path / "espeak-ng"),
        ffmpeg=str(tmp_path / "missing-ffmpeg"),
    )

    audio = await tts.synthesize("Проверка", audio_format="wav")

    assert audio.startswith(b"RIFF")


async def test_blank_text_produces_no_audio(tmp_path: Path) -> None:
    tts = LocalTextToSpeech(
        make_settings(),
        binary=str(tmp_path / "espeak-ng"),
        ffmpeg=str(tmp_path / "ffmpeg"),
    )

    assert await tts.synthesize("   ") == b""


async def test_missing_binary_is_a_configuration_error(tmp_path: Path) -> None:
    tts = LocalTextToSpeech(
        make_settings(),
        binary=str(tmp_path / "no-espeak"),
        ffmpeg=str(tmp_path / "ffmpeg"),
    )

    with pytest.raises(ConfigurationError):
        await tts.synthesize("текст")


async def test_failing_binary_is_a_synthesis_error(tmp_path: Path) -> None:
    broken = tmp_path / "espeak-ng"
    broken.write_text("#!/bin/sh\nexit 3\n")
    broken.chmod(0o755)
    tts = LocalTextToSpeech(make_settings(), binary=str(broken), ffmpeg=str(tmp_path / "ffmpeg"))

    with pytest.raises(SpeechSynthesisError):
        await tts.synthesize("текст")


def test_tts_backend_selection() -> None:
    assert make_settings(tts_backend="off").tts_enabled is False
    assert make_settings(tts_backend="sber", sber_tts_credentials="").tts_enabled is False
    assert make_settings(tts_backend="sber", sber_tts_credentials="key").tts_enabled is True
    assert make_settings(tts_backend="local", local_tts_enabled=True).tts_enabled is True
    assert make_settings(tts_backend="auto", local_tts_enabled=True).tts_enabled is True
    assert make_settings(tts_backend="auto", local_tts_enabled=False).tts_enabled is False


@pytest.mark.skipif(
    shutil.which("espeak-ng") is None or shutil.which("ffmpeg") is None,
    reason="espeak-ng and ffmpeg are not installed",
)
async def test_real_synthesis_produces_opus() -> None:
    tts = LocalTextToSpeech(make_settings(local_tts_enabled=True))

    audio = await tts.synthesize("Проверка синтеза", audio_format="opus")

    assert audio[:4] == b"OggS"
    assert len(audio) > 1000
    assert subprocess.run(["ffmpeg", "-version"], capture_output=True).returncode == 0
