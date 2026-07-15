/**
 * Build-time loader for generated site data (written by `bw export-blog`).
 * Falls back to empty structures so a fresh clone / CI builds cleanly
 * before any data has been exported.
 */

export interface AgentVerdict {
  agent: string;
  model: string | null;
  rating: string;
  confidence: number;
  one_liner: string;
  published: string;
  report_id: string;
}

export interface TickerData {
  symbol: string;
  name: string | null;
  sector: string | null;
  prices: [string, number][];
  composite: [string, number | null, number | null][];
  latest_indexes: Record<string, number>;
  latest_rank: number | null;
  latest_score: number | null;
  prev_score: number | null;
  verdicts: AgentVerdict[];
}

export interface IndexInfo {
  index_key: string;
  version: string;
  direction: string;
  description: string;
}

export interface ScorecardSummary {
  agent: string;
  evaluated: number;
  hit_rate: number | null;
  confidence_weighted_return: number | null;
  calibration: { bucket: string; n: number; hit_rate: number | null }[];
  checkpoints?: number[];
}

function load<T>(name: string, fallback: T): T {
  const files = import.meta.glob("../data/generated/*.json", { eager: true });
  const hit = Object.entries(files).find(([path]) => path.endsWith(`/${name}.json`));
  return hit ? ((hit[1] as { default: T }).default ?? fallback) : fallback;
}

export const tickers = (): TickerData[] => load<TickerData[]>("tickers", []);
export const indexes = (): IndexInfo[] => load<IndexInfo[]>("indexes", []);
export const scorecards = (): ScorecardSummary[] => load<ScorecardSummary[]>("scorecards", []);
