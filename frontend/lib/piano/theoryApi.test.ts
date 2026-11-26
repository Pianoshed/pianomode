import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  type ChordConstruct,
  type ChordIdentify,
  type ChordTypeInfo,
  type ScaleInfo,
  type ScaleResult,
  type VoicingsResult,
  constructChord,
  generateScale,
  identifyChord,
  listChordTypes,
  listScales,
  resetCatalogueCache,
} from "./theoryApi";
import cmaj7 from "./__fixtures__/chord-cmaj7.json";
import identifyCMajor from "./__fixtures__/identify-c-major.json";
import chordTypes from "./__fixtures__/chord-types.json";
import scales from "./__fixtures__/scales.json";
import fsharp from "./__fixtures__/scale-f-sharp-major.json";
import voicings from "./__fixtures__/voicings-cmaj7.json";

// These assignments are the contract check: if the API's response shape drifts from the types the
// piano relies on, regenerating the fixtures makes `npm run typecheck` fail here.
const chordFixture: ChordConstruct = cmaj7;
// JSON string literals widen to `string`, so the one enum field is narrowed by hand; the rest of
// the shape is still checked.
const identifyFixture: ChordIdentify = {
  ...identifyCMajor,
  status: identifyCMajor.status as ChordIdentify["status"],
};
const typesFixture: { types: ChordTypeInfo[] } = chordTypes;
const scalesFixture: { scales: ScaleInfo[] } = scales;
const scaleFixture: ScaleResult = fsharp;
const voicingsFixture: VoicingsResult = voicings;

function respond(status: number, body: unknown) {
  return vi.fn().mockResolvedValue({ status, ok: status < 400, json: async () => body });
}

describe("theory API client", () => {
  beforeEach(() => resetCatalogueCache());
  afterEach(() => vi.unstubAllGlobals());

  it("fixtures have the content the piano relies on", () => {
    expect(chordFixture.chord.tones.map((t) => t.name)).toEqual(["C", "E", "G", "B"]);
    expect(identifyFixture.candidates[0]?.symbol).toBe("C");
    expect(typesFixture.types.some((t) => t.id === "half_diminished7")).toBe(true);
    expect(scalesFixture.scales.some((s) => s.id === "dorian")).toBe(true);
    expect(scaleFixture.notes).toContain("E#");
    expect(voicingsFixture.voicings[0]?.voicing.right.length).toBeGreaterThan(0);
  });

  it("posts a chord request to the theory API", async () => {
    const fetchMock = respond(200, chordFixture);
    vi.stubGlobal("fetch", fetchMock);
    const r = await constructChord({ symbol: "Cmaj7", octave: 4 });
    expect(r.ok && r.data.chord.symbol).toBe("Cmaj7");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/theory/chords/construct");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ symbol: "Cmaj7", octave: 4 });
  });

  it("identifies notes with the spelling preference and a bounded candidate list", async () => {
    const fetchMock = respond(200, identifyFixture);
    vi.stubGlobal("fetch", fetchMock);
    await identifyChord([60, 64, 67], { prefer: "flats" });
    const body = JSON.parse((fetchMock.mock.calls[0] as [string, RequestInit])[1].body as string);
    expect(body).toEqual({ notes: [60, 64, 67], prefer: "flats", allow_rootless: false, max_candidates: 5 });
  });

  it("requests a scale with an octave so the keyboard notes come back", async () => {
    const fetchMock = respond(200, scaleFixture);
    vi.stubGlobal("fetch", fetchMock);
    await generateScale("F#", "major");
    expect(JSON.parse((fetchMock.mock.calls[0] as [string, RequestInit])[1].body as string)).toEqual({
      root: "F#",
      scale: "major",
      octave: 4,
    });
  });

  it("returns the server's stable error code and message for a musical error", async () => {
    vi.stubGlobal("fetch", respond(422, { error: { code: "unknown_quality", message: "Cmaj is ambiguous" } }));
    const r = await constructChord({ symbol: "Cmaj" });
    expect(r).toEqual({ ok: false, status: 422, code: "unknown_quality", message: "Cmaj is ambiguous" });
  });

  it("reports a network failure instead of throwing", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    const r = await constructChord({ symbol: "C" });
    expect(!r.ok && r.code).toBe("network_error");
  });

  it("fetches each catalogue once, and again after a failure", async () => {
    const ok = respond(200, typesFixture);
    vi.stubGlobal("fetch", ok);
    await listChordTypes();
    await listChordTypes();
    expect(ok).toHaveBeenCalledTimes(1);

    resetCatalogueCache();
    const bad = respond(500, { error: { code: "x", message: "y" } });
    vi.stubGlobal("fetch", bad);
    expect((await listScales()).ok).toBe(false);
    const good = respond(200, scalesFixture);
    vi.stubGlobal("fetch", good);
    expect((await listScales()).ok).toBe(true);
    expect(good).toHaveBeenCalledTimes(1);
  });
});
