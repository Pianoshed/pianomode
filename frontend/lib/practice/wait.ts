/** Wait mode: the music waits until the right notes are played. Pure state steps, no clock. */

export type WaitState = {
  index: number; // chord being asked for
  got: readonly number[]; // expected notes played so far for this chord
  wrongNow: number; // wrong notes pressed on this chord
  wrongTotal: number;
  firstTry: number; // chords finished without a wrong note
  done: boolean;
};

export type WaitStepInfo = { index: number; expected: number[] };

const same = (a: number, b: number, octaveEquivalent: boolean): boolean => (octaveEquivalent ? ((a % 12) + 12) % 12 === ((b % 12) + 12) % 12 : a === b);

/** Skip chords that ask nothing of the chosen hand (for example a rest in the left hand). */
function settle(state: WaitState, plan: readonly (readonly number[])[]): WaitState {
  let index = state.index;
  while (index < plan.length && (plan[index] as readonly number[]).length === 0) index += 1;
  return index >= plan.length ? { ...state, index: plan.length, got: [], done: true } : { ...state, index };
}

export function startWait(plan: readonly (readonly number[])[]): WaitState {
  return settle({ index: 0, got: [], wrongNow: 0, wrongTotal: 0, firstTry: 0, done: plan.length === 0 }, plan);
}

/** One note-on. A wanted note is kept until the chord is complete, then the next chord is asked
 *  for; any other note counts as a wrong note on this chord. Playing a wanted note twice is not
 *  a mistake. */
export function pressNote(state: WaitState, plan: readonly (readonly number[])[], midi: number, octaveEquivalent = false): WaitState {
  if (state.done) return state;
  const want = plan[state.index] as readonly number[];
  const hit = want.find((w) => same(w, midi, octaveEquivalent));
  if (hit === undefined) return { ...state, wrongNow: state.wrongNow + 1, wrongTotal: state.wrongTotal + 1 };
  if (state.got.includes(hit)) return state;
  const got = [...state.got, hit];
  if (got.length < want.length) return { ...state, got };
  const next: WaitState = { ...state, index: state.index + 1, got: [], wrongNow: 0, firstTry: state.firstTry + (state.wrongNow === 0 ? 1 : 0) };
  return settle(next, plan);
}

/** Chords that actually asked for notes, which is what the result is counted over. */
export const askedSteps = (plan: readonly (readonly number[])[]): number => plan.filter((p) => p.length > 0).length;
