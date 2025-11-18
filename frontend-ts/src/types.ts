// src/types.tsx
import { Data, Layout } from 'plotly.js';

// The AI-generated chart object
export interface PlotlyJson {
  data: Data[];
  layout: Partial<Layout>;
}

// The clean, tabular data for download
export type StructuredData = Record<string, any>[];

// Prominent source entry (for badges)
export interface ProminentSource {
  name: string;
  url?: string;
  tool?: string;
  type?: string;
  cached?: boolean;
}

// The source metadata for each chart (detailed)
export interface SourceEntry {
  tool: string;
  args?: any;
  cached?: boolean;
  fetched_at?: string;
  source?: {
    url?: string;
    name?: string;
  };
  url?: string;
  link?: string;
  name?: string;
}

// The new object for a single chart display
export interface ChartDisplay {
  plotlyChart: PlotlyJson;
  structuredData: StructuredData;
  sources?: SourceEntry[]; // original per-tool sources
  __prominent_sources?: ProminentSource[]; // badges to show first
  __evidence_key?: string; // key to fetch raw evidence CSV/JSON
  tool_raw_results?: any[]; // optional raw results from tools
  merged_rows?: Record<string, any>[]; // normalized merged rows
}

// The full API response
export interface DashboardData {
  charts: ChartDisplay[];
}
