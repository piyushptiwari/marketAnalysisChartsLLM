// types.tsx (update)
import { Data, Layout } from 'plotly.js';

export interface PlotlyJson {
  data: Data[];
  layout: Partial<Layout>;
}

export type StructuredData = Record<string, any>[];

export interface SourceEntry {
  tool: string;
  args?: Record<string, any>;
  cached?: boolean;
  fetched_at?: string;
}

export interface ChartDisplay {
  plotlyChart: PlotlyJson;
  structuredData: StructuredData;
  sources?: SourceEntry[]; // <- added
}

export interface DashboardData {
  charts: ChartDisplay[];
}
