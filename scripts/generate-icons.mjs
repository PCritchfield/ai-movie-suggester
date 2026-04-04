/**
 * Generate PWA icon assets from an SVG source.
 * Uses @napi-rs/canvas for server-side PNG rendering.
 *
 * Usage: node scripts/generate-icons.mjs
 */
import { createCanvas } from "@napi-rs/canvas";
import { writeFileSync, mkdirSync } from "fs";
import { join, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const outDir = join(__dirname, "..", "frontend", "public", "icons");
mkdirSync(outDir, { recursive: true });

/**
 * Draw the app icon on a canvas context at the given size.
 * Design: rounded-rect background with gradient, film strip motif, AI sparkle.
 */
function drawIcon(ctx, size, maskable = false) {
  const s = size;
  const pad = maskable ? s * 0.1 : 0; // maskable safe zone
  const inner = s - pad * 2;

  // Background — deep indigo gradient
  const grad = ctx.createLinearGradient(0, 0, s, s);
  grad.addColorStop(0, "#312e81"); // indigo-900
  grad.addColorStop(1, "#1e1b4b"); // indigo-950

  if (maskable) {
    // Fill entire canvas for maskable
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, s, s);
  } else {
    // Rounded rect
    const r = s * 0.18;
    ctx.beginPath();
    ctx.moveTo(r, 0);
    ctx.lineTo(s - r, 0);
    ctx.quadraticCurveTo(s, 0, s, r);
    ctx.lineTo(s, s - r);
    ctx.quadraticCurveTo(s, s, s - r, s);
    ctx.lineTo(r, s);
    ctx.quadraticCurveTo(0, s, 0, s - r);
    ctx.lineTo(0, r);
    ctx.quadraticCurveTo(0, 0, r, 0);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();
  }

  // Film strip — left side
  const stripX = pad + inner * 0.08;
  const stripW = inner * 0.12;
  const stripTop = pad + inner * 0.15;
  const stripBottom = pad + inner * 0.85;
  ctx.fillStyle = "rgba(255,255,255,0.15)";
  ctx.fillRect(stripX, stripTop, stripW, stripBottom - stripTop);

  // Sprocket holes
  const holeCount = 5;
  const holeH = inner * 0.04;
  const holeW = stripW * 0.6;
  const spacing = (stripBottom - stripTop - holeH) / (holeCount - 1);
  ctx.fillStyle = "#312e81";
  for (let i = 0; i < holeCount; i++) {
    const y = stripTop + i * spacing;
    ctx.fillRect(stripX + (stripW - holeW) / 2, y, holeW, holeH);
  }

  // Film strip — right side
  const stripX2 = pad + inner * 0.8;
  ctx.fillStyle = "rgba(255,255,255,0.15)";
  ctx.fillRect(stripX2, stripTop, stripW, stripBottom - stripTop);
  ctx.fillStyle = "#312e81";
  for (let i = 0; i < holeCount; i++) {
    const y = stripTop + i * spacing;
    ctx.fillRect(stripX2 + (stripW - holeW) / 2, y, holeW, holeH);
  }

  // Center play triangle / movie symbol
  const cx = s / 2;
  const cy = s / 2;
  const triSize = inner * 0.22;
  ctx.beginPath();
  ctx.moveTo(cx - triSize * 0.4, cy - triSize * 0.55);
  ctx.lineTo(cx + triSize * 0.6, cy);
  ctx.lineTo(cx - triSize * 0.4, cy + triSize * 0.55);
  ctx.closePath();
  ctx.fillStyle = "rgba(255,255,255,0.9)";
  ctx.fill();

  // AI sparkle — small 4-point star, upper right
  const sx = pad + inner * 0.72;
  const sy = pad + inner * 0.22;
  const starR = inner * 0.08;
  ctx.fillStyle = "#c4b5fd"; // violet-300
  ctx.beginPath();
  // 4-point star
  ctx.moveTo(sx, sy - starR);
  ctx.quadraticCurveTo(sx + starR * 0.15, sy - starR * 0.15, sx + starR, sy);
  ctx.quadraticCurveTo(sx + starR * 0.15, sy + starR * 0.15, sx, sy + starR);
  ctx.quadraticCurveTo(sx - starR * 0.15, sy + starR * 0.15, sx - starR, sy);
  ctx.quadraticCurveTo(sx - starR * 0.15, sy - starR * 0.15, sx, sy - starR);
  ctx.closePath();
  ctx.fill();

  // Smaller sparkle
  const sx2 = pad + inner * 0.62;
  const sy2 = pad + inner * 0.14;
  const starR2 = inner * 0.04;
  ctx.beginPath();
  ctx.moveTo(sx2, sy2 - starR2);
  ctx.quadraticCurveTo(
    sx2 + starR2 * 0.15,
    sy2 - starR2 * 0.15,
    sx2 + starR2,
    sy2
  );
  ctx.quadraticCurveTo(
    sx2 + starR2 * 0.15,
    sy2 + starR2 * 0.15,
    sx2,
    sy2 + starR2
  );
  ctx.quadraticCurveTo(
    sx2 - starR2 * 0.15,
    sy2 + starR2 * 0.15,
    sx2 - starR2,
    sy2
  );
  ctx.quadraticCurveTo(
    sx2 - starR2 * 0.15,
    sy2 - starR2 * 0.15,
    sx2,
    sy2 - starR2
  );
  ctx.closePath();
  ctx.fill();
}

// Generate standard icons
for (const size of [192, 512]) {
  const canvas = createCanvas(size, size);
  const ctx = canvas.getContext("2d");
  drawIcon(ctx, size, false);
  const buf = canvas.toBuffer("image/png");
  const path = join(outDir, `icon-${size}x${size}.png`);
  writeFileSync(path, buf);
  console.log(`Created ${path} (${buf.length} bytes)`);
}

// Maskable 512
{
  const size = 512;
  const canvas = createCanvas(size, size);
  const ctx = canvas.getContext("2d");
  drawIcon(ctx, size, true);
  const buf = canvas.toBuffer("image/png");
  const path = join(outDir, `icon-512x512-maskable.png`);
  writeFileSync(path, buf);
  console.log(`Created ${path} (${buf.length} bytes)`);
}

// Apple touch icon 180x180
{
  const size = 180;
  const canvas = createCanvas(size, size);
  const ctx = canvas.getContext("2d");
  drawIcon(ctx, size, false);
  const buf = canvas.toBuffer("image/png");
  const path = join(outDir, `apple-touch-icon.png`);
  writeFileSync(path, buf);
  console.log(`Created ${path} (${buf.length} bytes)`);
}

// Favicon 32x32
{
  const size = 32;
  const canvas = createCanvas(size, size);
  const ctx = canvas.getContext("2d");
  drawIcon(ctx, size, false);
  const buf = canvas.toBuffer("image/png");
  const path = join(outDir, `favicon-32x32.png`);
  writeFileSync(path, buf);
  console.log(`Created ${path} (${buf.length} bytes)`);
}

console.log("\nAll icons generated successfully.");
