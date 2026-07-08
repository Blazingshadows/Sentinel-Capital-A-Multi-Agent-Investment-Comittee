import { formatCurrency, formatDate } from "../format";
import type { PortfolioSnapshotRow } from "../types";

const SVG_NS = "http://www.w3.org/2000/svg";
const PADDING = { top: 16, right: 16, bottom: 24, left: 56 };

function niceTicks(min: number, max: number, count = 4): number[] {
  if (min === max) return [min];
  const span = max - min;
  const rawStep = span / count;
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const residual = rawStep / magnitude;
  const step = (residual > 5 ? 10 : residual > 2 ? 5 : residual > 1 ? 2 : 1) * magnitude;
  const start = Math.floor(min / step) * step;
  const ticks: number[] = [];
  for (let value = start; value <= max + step; value += step) ticks.push(value);
  return ticks;
}

/** Single-series line chart of portfolio value over time: 2px line, ~10%
 * opacity area wash, end-dot with a surface ring and direct label, hairline
 * gridlines, and a crosshair+tooltip that snaps to the nearest point. No
 * legend -- a single series is already named by the section title. */
export function renderPortfolioChart(container: HTMLElement, data: PortfolioSnapshotRow[]): void {
  container.innerHTML = "";

  if (data.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "No portfolio history yet — run a cycle to get started.";
    container.appendChild(empty);
    return;
  }

  const width = container.clientWidth || 800;
  const height = 260;
  const plotWidth = width - PADDING.left - PADDING.right;
  const plotHeight = height - PADDING.top - PADDING.bottom;

  const values = data.map((row) => row.portfolio_value);
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const ticks = niceTicks(minValue, maxValue);
  const yMin = Math.min(minValue, ticks[0]);
  const yMax = Math.max(maxValue, ticks[ticks.length - 1]);

  const xForIndex = (i: number) => PADDING.left + (data.length === 1 ? plotWidth / 2 : (i / (data.length - 1)) * plotWidth);
  const yForValue = (v: number) => PADDING.top + plotHeight - ((v - yMin) / (yMax - yMin || 1)) * plotHeight;

  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("width", "100%");
  svg.setAttribute("height", String(height));
  svg.style.display = "block";

  const gridGroup = document.createElementNS(SVG_NS, "g");
  for (const tick of ticks) {
    const y = yForValue(tick);
    const line = document.createElementNS(SVG_NS, "line");
    line.setAttribute("x1", String(PADDING.left));
    line.setAttribute("x2", String(width - PADDING.right));
    line.setAttribute("y1", String(y));
    line.setAttribute("y2", String(y));
    line.setAttribute("stroke", "var(--gridline)");
    line.setAttribute("stroke-width", "1");
    gridGroup.appendChild(line);

    const label = document.createElementNS(SVG_NS, "text");
    label.setAttribute("x", String(PADDING.left - 8));
    label.setAttribute("y", String(y + 4));
    label.setAttribute("text-anchor", "end");
    label.setAttribute("fill", "var(--text-muted)");
    label.setAttribute("font-size", "11px");
    label.textContent = tick >= 1000 ? `${(tick / 1000).toFixed(0)}K` : String(Math.round(tick));
    gridGroup.appendChild(label);
  }
  svg.appendChild(gridGroup);

  const linePoints = data.map((row, i) => [xForIndex(i), yForValue(row.portfolio_value)] as const);

  const areaPath = document.createElementNS(SVG_NS, "path");
  const areaD =
    `M ${linePoints[0][0]},${PADDING.top + plotHeight} ` +
    linePoints.map(([x, y]) => `L ${x},${y}`).join(" ") +
    ` L ${linePoints[linePoints.length - 1][0]},${PADDING.top + plotHeight} Z`;
  areaPath.setAttribute("d", areaD);
  areaPath.setAttribute("fill", "var(--series-1-wash)");
  svg.appendChild(areaPath);

  const linePath = document.createElementNS(SVG_NS, "path");
  linePath.setAttribute("d", `M ${linePoints.map(([x, y]) => `${x},${y}`).join(" L ")}`);
  linePath.setAttribute("fill", "none");
  linePath.setAttribute("stroke", "var(--series-1)");
  linePath.setAttribute("stroke-width", "2");
  linePath.setAttribute("stroke-linejoin", "round");
  linePath.setAttribute("stroke-linecap", "round");
  svg.appendChild(linePath);

  const [lastX, lastY] = linePoints[linePoints.length - 1];
  const endRing = document.createElementNS(SVG_NS, "circle");
  endRing.setAttribute("cx", String(lastX));
  endRing.setAttribute("cy", String(lastY));
  endRing.setAttribute("r", "6");
  endRing.setAttribute("fill", "var(--surface-1)");
  svg.appendChild(endRing);
  const endDot = document.createElementNS(SVG_NS, "circle");
  endDot.setAttribute("cx", String(lastX));
  endDot.setAttribute("cy", String(lastY));
  endDot.setAttribute("r", "4");
  endDot.setAttribute("fill", "var(--series-1)");
  svg.appendChild(endDot);

  const endLabel = document.createElementNS(SVG_NS, "text");
  endLabel.setAttribute("x", String(Math.min(lastX + 8, width - PADDING.right - 60)));
  endLabel.setAttribute("y", String(lastY - 10));
  endLabel.setAttribute("fill", "var(--text-primary)");
  endLabel.setAttribute("font-size", "12px");
  endLabel.setAttribute("font-weight", "600");
  endLabel.textContent = formatCurrency(values[values.length - 1]);
  svg.appendChild(endLabel);

  const crosshair = document.createElementNS(SVG_NS, "line");
  crosshair.setAttribute("y1", String(PADDING.top));
  crosshair.setAttribute("y2", String(PADDING.top + plotHeight));
  crosshair.setAttribute("stroke", "var(--baseline)");
  crosshair.setAttribute("stroke-width", "1");
  crosshair.style.opacity = "0";
  svg.appendChild(crosshair);

  const hoverDot = document.createElementNS(SVG_NS, "circle");
  hoverDot.setAttribute("r", "4");
  hoverDot.setAttribute("fill", "var(--series-1)");
  hoverDot.setAttribute("stroke", "var(--surface-1)");
  hoverDot.setAttribute("stroke-width", "2");
  hoverDot.style.opacity = "0";
  svg.appendChild(hoverDot);

  const hitArea = document.createElementNS(SVG_NS, "rect");
  hitArea.setAttribute("x", String(PADDING.left));
  hitArea.setAttribute("y", String(PADDING.top));
  hitArea.setAttribute("width", String(plotWidth));
  hitArea.setAttribute("height", String(plotHeight));
  hitArea.setAttribute("fill", "transparent");
  svg.appendChild(hitArea);

  container.appendChild(svg);

  const tooltip = document.createElement("div");
  tooltip.className = "chart-tooltip";
  container.appendChild(tooltip);

  hitArea.addEventListener("pointermove", (event) => {
    const rect = svg.getBoundingClientRect();
    const pointerX = ((event.clientX - rect.left) / rect.width) * width;
    let nearest = 0;
    let nearestDist = Infinity;
    linePoints.forEach(([x], i) => {
      const dist = Math.abs(x - pointerX);
      if (dist < nearestDist) {
        nearestDist = dist;
        nearest = i;
      }
    });

    const [x, y] = linePoints[nearest];
    crosshair.setAttribute("x1", String(x));
    crosshair.setAttribute("x2", String(x));
    crosshair.style.opacity = "1";
    hoverDot.setAttribute("cx", String(x));
    hoverDot.setAttribute("cy", String(y));
    hoverDot.style.opacity = "1";

    const row = data[nearest];
    const dateEl = document.createElement("div");
    dateEl.className = "date";
    dateEl.textContent = formatDate(row.ts);
    const valueEl = document.createElement("div");
    valueEl.className = "value";
    valueEl.textContent = formatCurrency(row.portfolio_value);
    tooltip.replaceChildren(dateEl, valueEl);

    const tooltipX = Math.min(Math.max(x - 40, 0), width - 130);
    tooltip.style.left = `${tooltipX}px`;
    tooltip.style.top = `${Math.max(y - 56, 0)}px`;
    tooltip.style.opacity = "1";
  });

  hitArea.addEventListener("pointerleave", () => {
    crosshair.style.opacity = "0";
    hoverDot.style.opacity = "0";
    tooltip.style.opacity = "0";
  });
}
