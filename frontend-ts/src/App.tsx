// App.tsx (updated)
import React, { useState, useCallback, FormEvent } from 'react';
import Plot from 'react-plotly.js';
import './App.css';
import { DashboardData, ChartDisplay, StructuredData } from './types';
import * as XLSX from 'xlsx';
import { jsPDF } from 'jspdf';

function App() {
  const [dashboardData, setDashboardData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [topic, setTopic] = useState<string>("Global electric vehicle (EV) market analysis");

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    setDashboardData(null);
    const encodedTopic = encodeURIComponent(topic);

    try {
      const response = await fetch(`http://localhost:8001/api/get-dashboard-data?topic=${encodedTopic}`);
      if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
      const data: DashboardData = await response.json();
      if (!data.charts || data.charts.length === 0) throw new Error("AI returned an empty or invalid dashboard.");
      setDashboardData(data);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [topic]);

  const handleTopicChange = (e: React.ChangeEvent<HTMLInputElement>) => setTopic(e.target.value);
  const handleFormSubmit = (e: FormEvent) => { e.preventDefault(); fetchData(); };

  const getNormalizedLayout = (chart: ChartDisplay, index: number) => {
    const defaultLayout = {
      autosize: true,
      title: { text: `Chart ${index + 1}` },
      paper_bgcolor: 'white',
      plot_bgcolor: '#fafafa',
    };
    const aiLayout = chart.plotlyChart.layout || {};
    const newLayout = { ...defaultLayout, ...aiLayout };
    const titleValue = newLayout.title || defaultLayout.title.text;
    newLayout.title = (typeof titleValue === 'string') ? { text: titleValue } : titleValue;
    return newLayout;
  };

  const handleJsonDownload = (data: StructuredData, filename: string) => {
    if (data.length === 0) return;
    const jsonString = JSON.stringify(data, null, 2);
    const blob = new Blob([jsonString], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${filename}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const handleExcelDownload = (data: StructuredData, filename: string) => {
    if (data.length === 0) return;
    const ws = XLSX.utils.json_to_sheet(data);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "Data");
    XLSX.writeFile(wb, `${filename}.xlsx`);
  };

  const getChartTitleAsFilename = (chart: ChartDisplay, index: number): string => {
    const layout = chart.plotlyChart.layout || {};
    let title = `chart-${index + 1}`;
    if (typeof layout.title === 'string') title = layout.title;
    else if (typeof layout.title === 'object' && layout.title.text) title = layout.title.text;
    return title.toLowerCase().replace(/[^a-z0-9]/g, '-').substring(0, 50);
  }

  // --- Full report export: Excel workbook (one sheet per chart) + PDF summary ---
  const handleDownloadFullReport = () => {
    if (!dashboardData) return;

    // Excel workbook
    const wb = XLSX.utils.book_new();
    dashboardData.charts.forEach((chart, i) => {
      const sheetName = (getChartTitleAsFilename(chart, i) || `chart-${i+1}`).substring(0, 31);
      const data = chart.structuredData && chart.structuredData.length > 0 ? chart.structuredData : [{ note: "No structured data available" }];
      const ws = XLSX.utils.json_to_sheet(data);
      XLSX.utils.book_append_sheet(wb, ws, sheetName);
    });
    const excelFilename = `${topic.replace(/[^a-z0-9]/gi, '_').substring(0,40)}_report.xlsx`;
    XLSX.writeFile(wb, excelFilename);

    // Simple PDF summary
    const doc = new jsPDF({ unit: 'pt', format: 'a4' });
    const margin = 40;
    let y = 60;
    doc.setFontSize(16);
    doc.text(`Research Report`, margin, y);
    y += 24;
    doc.setFontSize(12);
    doc.text(`Topic: ${topic}`, margin, y);
    y += 18;
    doc.text(`Generated: ${new Date().toLocaleString()}`, margin, y);
    y += 22;

    dashboardData.charts.forEach((chart, i) => {
      const title = (chart.plotlyChart.layout && (chart.plotlyChart.layout.title as any)?.text) || `Chart ${i+1}`;
      doc.setFontSize(13);
      doc.text(`${i+1}. ${title}`, margin, y);
      y += 16;
      doc.setFontSize(10);
      // sources
      if (chart.sources && chart.sources.length > 0) {
        const sourcesText = chart.sources.map(s => `${s.tool}${s.fetched_at ? ' @ ' + s.fetched_at.split('T')[0] : ''}`).join(', ');
        doc.text(`Sources: ${sourcesText}`, margin + 12, y);
      } else {
        doc.text(`Sources: (not provided)`, margin + 12, y);
      }
      y += 22;
      // prevent overflow: add a page if needed
      if (y > 720) {
        doc.addPage();
        y = 60;
      }
    });

    const pdfFilename = `${topic.replace(/[^a-z0-9]/gi, '_').substring(0,40)}_summary.pdf`;
    doc.save(pdfFilename);
  };

  return (
    <div className="App">
      <header className="App-header">
        <h1>AI-Powered Research Dashboard</h1>
      </header>

      <div className="query-form-container">
        <form onSubmit={handleFormSubmit}>
          <input
            type="text"
            value={topic}
            onChange={handleTopicChange}
            placeholder="Enter research topic..."
          />
          <button type="submit" disabled={loading}>
            {loading ? 'Analyzing...' : 'Generate Dashboard'}
          </button>
          <button type="button" onClick={handleDownloadFullReport} disabled={!dashboardData}>
            Download Full Report (Excel + PDF)
          </button>
        </form>
      </div>



      <div className="dashboard-grid">
        {loading && <div className="loading-spinner-full"></div>}
        {error && <div className="error-message">Error: {error}. Is the backend running?</div>}

        {dashboardData && dashboardData.charts.map((chartDisplay, index) => {
          const hasData = chartDisplay.plotlyChart.data && chartDisplay.plotlyChart.data.length > 0;
          const layout = getNormalizedLayout(chartDisplay, index);
          const titleText = layout.title && typeof layout.title === 'object' ? layout.title.text : `Chart ${index + 1}`;

          return (
            <div className="chart-card" key={index}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <h3 style={{ margin: 0 }}>{titleText}</h3>
                <div>
                  <button
                    onClick={() => handleJsonDownload(chartDisplay.structuredData, getChartTitleAsFilename(chartDisplay, index))}
                    disabled={chartDisplay.structuredData.length === 0}
                  >
                    Download JSON
                  </button>
                  <button
                    onClick={() => handleExcelDownload(chartDisplay.structuredData, getChartTitleAsFilename(chartDisplay, index))}
                    disabled={chartDisplay.structuredData.length === 0}
                  >
                    Download Excel
                  </button>
                </div>
              </div>

              <div className="chart-container">
                {hasData ? (
                  <Plot
                    data={chartDisplay.plotlyChart.data}
                    layout={layout}
                    style={{ width: '100%', height: '100%' }}
                    useResizeHandler={true}
                  />
                ) : (
                  <div className="chart-error-message">
                    <span>No data was generated for this chart.</span>
                    <small>Topic: {titleText}</small>
                  </div>
                )}
              </div>
              {chartDisplay.__prominent_sources && chartDisplay.__prominent_sources.length > 0 && (
              <div style={{ paddingTop: 10 }}>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                  {chartDisplay.__prominent_sources.map((p: any, i: number) => (
                    <a key={i}
                      href={p.url || '#'}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{
                        padding: '6px 10px',
                        background: '#fff',
                        border: '1px solid #ddd',
                        borderRadius: 6,
                        textDecoration: 'none',
                        color: '#333',
                        boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
                        display: 'inline-flex',
                        flexDirection: 'column',
                        minWidth: 140
                      }}>
                      <strong style={{fontSize: 13}}>{p.name}</strong>
                      <small style={{opacity: 0.8}}>{p.type || p.tool}{p.cached ? ' • cached' : ''}</small>
                    </a>
                  ))}

                  {/* View Raw Evidence & CSV buttons */}
                  <div style={{ display: 'flex', gap: 8, marginLeft: 6 }}>
                    <button onClick={async () => {
                      const key = chartDisplay.__evidence_key;
                      if (!key) { alert("No evidence available for this chart."); return; }
                      const url = `http://localhost:8001/api/evidence/${key}`;
                      window.open(url, "_blank");
                    }}>
                      View raw evidence
                    </button>

                    <button onClick={async () => {
                      const key = chartDisplay.__evidence_key;
                      if (!key) { alert("No evidence available for this chart."); return; }
                      window.location.href = `http://localhost:8001/api/evidence/${key}/csv`;
                    }}>
                      Download merged CSV
                    </button>
                  </div>
                </div>
              </div>
            )}
              <div style={{ paddingTop: 12, borderTop: '1px solid #eee', marginTop: 10 }}>
                <strong>Data Sources Used:</strong>
                {chartDisplay.sources && chartDisplay.sources.length > 0 ? (
                  <div style={{ marginTop: 8 }}>
                    <ul style={{ paddingLeft: 16 }}>
                      {chartDisplay.sources.map((s: any, si: number) => {
                        const url = s.source?.url || s.source?.link || (s as any).url || (s as any).link;
                        const name = s.source?.name || s.tool || s.name || `source-${si+1}`;
                        return (
                          <li key={si} style={{ marginBottom: 6 }}>
                            <small>
                              {url ? (
                                <a href={url} target="_blank" rel="noopener noreferrer">{name}</a>
                              ) : <span>{name}</span>}
                              {s.cached ? ' (cached)' : ''}
                              {s.fetched_at ? ` — ${new Date(s.fetched_at).toLocaleString()}` : ''}
                              {s.args ? ` — ${JSON.stringify(s.args)}` : ''}
                            </small>
                          </li>
                        );
                      })}
                    </ul>

                    <div style={{ display: 'flex', gap: 8, marginTop: 6 }}>
                      <button onClick={() => {
                        (chartDisplay.sources || []).forEach((s: any) => {
                          const url = s.source?.url || s.url || s.link;
                          if (url) window.open(url, "_blank");
                        });
                      }}>
                        Open all sources
                      </button>

                      <button onClick={async () => {
                        // Deep Dive trigger: ask user for competitor list (quick flow)
                        const competitors = prompt("Enter competitors (comma separated), or leave blank to use chart title:");
                        const compList = competitors ? competitors.split(",").map((c)=>c.trim()).filter(Boolean) : [ (chartDisplay.plotlyChart?.layout as any)?.title?.text || `chart` ];
                        try {
                          const resp = await fetch("http://localhost:8001/api/deep-dive", {
                            method: "POST",
                            headers: {"Content-Type":"application/json"},
                            body: JSON.stringify({ topic: compList.join(","), competitors: compList })
                          });
                          const deep = await resp.json();
                          const w = window.open("");
                          w!.document.write("<pre>" + JSON.stringify(deep.merged || deep, null, 2) + "</pre>");
                        } catch (err) {
                          alert("Deep dive failed: " + err);
                        }
                      }}>
                        Deep Dive
                      </button>
                    </div>
                  </div>
                ) : (
                  <div style={{ color: '#666', marginTop: 8 }}><small>No sources available.</small></div>
                )}
              </div>


            </div>
          );
        })}
      </div>
    </div>
  );
}
export default App;
