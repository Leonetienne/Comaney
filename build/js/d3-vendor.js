import * as d3 from 'd3';

// project_insights.html / buddy_summary.html use the d3 global directly
// from inline <script> blocks, so expose it the same way the CDN build did.
window.d3 = d3;
