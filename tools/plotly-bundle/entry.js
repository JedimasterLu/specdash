// Plotly core plus only the trace types SpecDash uses (line plots and the detector image).
// The version of plotly.js must match the one bundled with the installed plotly Python package
// (plotly.offline.get_plotlyjs_version()), which is what dash's dcc.Graph is built against.
var Plotly = require("plotly.js/lib/core");
Plotly.register([require("plotly.js/lib/scatter"), require("plotly.js/lib/heatmap")]);
window.Plotly = Plotly;
module.exports = Plotly;
