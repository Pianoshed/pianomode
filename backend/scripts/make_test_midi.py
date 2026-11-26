"""Write small Standard MIDI Files for tests, and export the engine's analysis of the same music.

The writer here is independent of the TypeScript reader in frontend/lib/midi, so a test that reads
these files with the reader and compares the result with the notes written here checks both.

    cd backend && PYTHONPATH=. python scripts/make_test_midi.py
"""

import json
import struct
from pathlib import Path
from typing import Any

OUT = Path(__file__).resolve().parents[2] / "frontend" / "lib" / "midi" / "__fixtures__"
PPQ = 480
BAR = PPQ * 4


def vlq(value: int) -> bytes:
    out = [value & 0x7F]
    value >>= 7
    while value:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    return bytes(reversed(out))


def meta(kind: int, data: bytes) -> bytes:
    return bytes([0xFF, kind]) + vlq(len(data)) + data


def track_chunk(events: list[tuple[int, bytes]], *, running_status: bool = False) -> bytes:
    """events: (absolute tick, raw bytes). Note-offs sort before note-ons at the same tick."""
    ordered = sorted(events, key=lambda e: (e[0], 0 if e[1][0] & 0xF0 == 0x80 else 1))
    body = b""
    now = 0
    last_status: int | None = None
    for tick, raw in ordered:
        body += vlq(tick - now)
        now = tick
        status = raw[0]
        if running_status and status < 0xF0 and status == last_status:
            body += raw[1:]
        else:
            body += raw
        last_status = status if status < 0xF0 else None
    body += vlq(0) + meta(0x2F, b"")
    return b"MTrk" + struct.pack(">I", len(body)) + body


def header(fmt: int, ntrks: int, division: int = PPQ) -> bytes:
    return b"MThd" + struct.pack(">IHHH", 6, fmt, ntrks, division)


def note(tick: int, channel: int, key: int, velocity: int, length: int) -> list[tuple[int, bytes]]:
    return [
        (tick, bytes([0x90 | channel, key, velocity])),
        (tick + length, bytes([0x80 | channel, key, 0])),
    ]


# C major: I - vi - IV - V7, one chord per bar. Right hand plays the chords, left hand the bass.
RIGHT = [(60, 64, 67), (57, 60, 64), (60, 65, 69), (59, 62, 65, 67)]
LEFT = [48, 45, 41, 43]


def notes_written() -> list[dict[str, Any]]:
    """Every note in the fixtures: tick, length, pitch, velocity, track, channel."""
    out = []
    for bar, (chord, bass) in enumerate(zip(RIGHT, LEFT, strict=True)):
        for pitch in chord:
            out.append(
                {
                    "tick": bar * BAR,
                    "length": BAR - 20,
                    "note": pitch,
                    "velocity": 80,
                    "track": 1,
                    "channel": 0,
                }
            )
        out.append(
            {
                "tick": bar * BAR,
                "length": BAR - 20,
                "note": bass,
                "velocity": 90,
                "track": 2,
                "channel": 0,
            }
        )
    return out


def conductor() -> list[tuple[int, bytes]]:
    return [
        (0, meta(0x03, b"Conductor")),
        (0, meta(0x51, struct.pack(">I", 600_000)[1:])),  # 100 BPM
        (0, meta(0x58, bytes([4, 2, 24, 8]))),  # 4/4
    ]


def two_hand_file() -> bytes:
    right = [(0, meta(0x03, b"Right hand")), (0, bytes([0xC0, 0]))]
    left = [(0, meta(0x03, b"Left hand")), (0, bytes([0xC0, 0]))]
    for n in notes_written():
        (right if n["track"] == 1 else left).extend(
            note(n["tick"], n["channel"], n["note"], n["velocity"], n["length"])
        )
    return header(1, 3) + track_chunk(conductor()) + track_chunk(right) + track_chunk(left)


def single_track_file() -> bytes:
    events = conductor()
    for n in notes_written():
        events.extend(note(n["tick"], n["channel"], n["note"], n["velocity"], n["length"]))
    return header(0, 1) + track_chunk(events, running_status=True)


def request_events() -> list[dict[str, Any]]:
    events = []
    for n in notes_written():
        events.append(
            {
                "tick": n["tick"],
                "kind": "note_on",
                "note": n["note"],
                "velocity": n["velocity"],
                "channel": 0,
                "track": n["track"],
            }
        )
        events.append(
            {
                "tick": n["tick"] + n["length"],
                "kind": "note_off",
                "note": n["note"],
                "velocity": 0,
                "channel": 0,
                "track": n["track"],
            }
        )
    return events


def main() -> None:
    from app.schemas import theory as s
    from app.services import theory_service as svc

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "c-am-f-g.mid").write_bytes(two_hand_file())
    (OUT / "single-track.mid").write_bytes(single_track_file())
    request = {
        "ppq": PPQ,
        "events": request_events(),
        "tempo_changes": [{"tick": 0, "bpm": 100}],
        "time_signatures": [{"tick": 0, "numerator": 4, "denominator": 4}],
    }
    (OUT / "c-am-f-g.request.json").write_text(json.dumps(request, indent=1) + "\n")
    response = svc.analyze_midi(s.MidiAnalyzeRequest(**request))
    (OUT / "c-am-f-g.analysis.json").write_text(
        json.dumps(response.model_dump(mode="json"), indent=1, ensure_ascii=False) + "\n"
    )
    print("wrote", sorted(p.name for p in OUT.iterdir()))


if __name__ == "__main__":
    main()
