// ECharts ۵٫۵٫۱ فقط با آنچه نمودارهای نقشه لازم دارند (map-charts.js)؛ خروجی را بالای همین پوشه با build.sh بسازید.
import * as echarts from "echarts/core";
import {BarChart, LineChart, PieChart, RadarChart, SankeyChart, ScatterChart} from "echarts/charts";
import {AriaComponent, GridComponent, LegendComponent, RadarComponent, TooltipComponent} from "echarts/components";
import {SVGRenderer} from "echarts/renderers";

echarts.use([BarChart, LineChart, PieChart, RadarChart, SankeyChart, ScatterChart, AriaComponent, GridComponent,
  LegendComponent, RadarComponent, TooltipComponent, SVGRenderer]);
window.echarts = echarts;
