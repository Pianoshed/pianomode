/** Typed calls to the lessons API. Lesson text is authored; every note, numeral and playback
 *  step in the examples is built by the theory engine on the server. */

import { type ApiResult, api } from "@/lib/api";

export type Level = "beginner" | "intermediate" | "advanced" | "expert";
export type LessonStatus = "not_started" | "in_progress" | "practised";
export type ExampleType = "chord" | "scale" | "interval" | "sequence";

export type ExampleItem = { label: string; notes: string[]; midi: number[]; detail: string | null };
export type PlayStep = { notes: number[]; start: number; duration: number; item: number };
export type Example = { type: ExampleType; caption: string; items: ExampleItem[]; play: PlayStep[]; tempo: number };
export type Section = { heading: string; body: string[]; examples: Example[] };
export type Goal = {
  kind: string;
  title: string;
  difficulty: string;
  goal: number;
  correct: number;
  attempted: boolean;
  met: boolean;
  ear_training: boolean;
};
export type LessonLink = { id: string; title: string; status: LessonStatus };
export type LessonSummary = {
  id: string;
  title: string;
  level: Level;
  summary: string;
  tags: string[];
  prerequisites: string[];
  unmet_prerequisites: string[];
  status: LessonStatus;
  goals_met: number;
  goals_total: number;
};
export type LessonList = { items: LessonSummary[]; note: string };
export type LessonDetail = {
  id: string;
  title: string;
  level: Level;
  summary: string;
  revision: number;
  tags: string[];
  objectives: string[];
  sections: Section[];
  practice: Goal[];
  status: LessonStatus;
  prerequisites: LessonLink[];
  next: LessonLink[];
  movement_slug: string | null;
};

export const listLessons = (): Promise<ApiResult<LessonList>> => api("/api/v1/lessons");
export const getLesson = (id: string): Promise<ApiResult<LessonDetail>> => api(`/api/v1/lessons/${encodeURIComponent(id)}`);
