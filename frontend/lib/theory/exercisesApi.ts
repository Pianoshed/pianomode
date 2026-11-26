/** Typed calls to the exercise API. Questions and grading come from the theory engine on the
 *  server; the browser only shows them and sends answers back. */

import { type ApiResult, api } from "@/lib/api";

const BASE = "/api/v1/theory/exercises";

export type Difficulty = "beginner" | "intermediate" | "advanced" | "expert";
export type AnswerFormat = "choice" | "text" | "note_names" | "note_set" | "chord_symbols";
export type Answer = string | string[] | number[];

export type ExerciseKind = {
  kind: string;
  title: string;
  topic: string;
  objective: string;
  prerequisites: string[];
  ear_training: boolean;
};
export type KindList = { difficulties: Difficulty[]; kinds: ExerciseKind[] };
export type PlayEvent = { notes: number[]; start: number; duration: number };
export type Exercise = {
  id: string;
  kind: string;
  difficulty: Difficulty;
  seed: number;
  topic: string;
  prompt: string;
  answer_format: AnswerFormat;
  answer_help: string;
  choices: string[];
  show: number[];
  play: PlayEvent[];
  tempo: number;
  hint: string;
};
export type GradeStatus = "correct" | "enharmonic" | "partial" | "incorrect" | "unreadable";
export type Grade = {
  exercise_id: string;
  status: GradeStatus;
  correct: boolean;
  feedback: string;
  correct_answer: string;
  explanation: string;
  items: { index: number; given: string; correct: boolean; expected: string }[];
};
export type KindProgress = {
  kind: string;
  difficulty: Difficulty;
  attempts: number;
  correct: number;
  recent_attempts: number;
  recent_correct: number;
  last_at: string;
};

export const listKinds = (): Promise<ApiResult<KindList>> => api(`${BASE}/kinds`);
export const getProgress = (): Promise<ApiResult<{ items: KindProgress[]; note: string }>> => api(`${BASE}/progress`);

export function newExercise(kind: string, difficulty: Difficulty, seed: number = randomSeed()): Promise<ApiResult<{ exercises: Exercise[] }>> {
  return api(`${BASE}/generate`, { method: "POST", body: { kind, difficulty, seed, count: 1 } });
}
export function gradeExercise(exerciseId: string, answer: Answer): Promise<ApiResult<Grade>> {
  return api(`${BASE}/validate`, { method: "POST", body: { exercise_id: exerciseId, answer } });
}

/** A seed the server will accept (0 to 2^31 - 1). */
export function randomSeed(random: () => number = Math.random): number {
  return Math.floor(random() * 2 ** 31);
}
