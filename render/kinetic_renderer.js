#!/usr/bin/env node
/**
 * render/kinetic_renderer.js — Vector & Kinetic Motion Graphic Generator
 *
 * Generates alpha-channel transparent vector graphics and kinetic overlays
 * (chapter badges, glow cards, animated audio wave representations)
 * for FFmpeg compositing in YouTube Shorts.
 */

import fs from 'node:fs';
import path from 'node:path';

function parseArgs() {
  const args = process.argv.slice(2);
  const params = {
    text: 'TOPATO FACTS',
    output: 'kinetic_badge.svg',
    style: 'neon',
    width: 1080,
    height: 1920,
    accent: '#FF3366',
  };

  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--text' && args[i + 1]) params.text = args[++i];
    else if (args[i] === '--output' && args[i + 1]) params.output = args[++i];
    else if (args[i] === '--style' && args[i + 1]) params.style = args[++i];
    else if (args[i] === '--accent' && args[i + 1]) params.accent = args[++i];
  }
  return params;
}

function generateNeonBadgeSVG(text, accentColor) {
  const cleanText = text.replace(/[<>&"]/g, '');
  return `<?xml version="1.0" encoding="UTF-8"?>
<svg width="1080" height="1920" viewBox="0 0 1080 1920" fill="none" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <filter id="neonGlow" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="8" result="blur1" />
      <feGaussianBlur stdDeviation="20" result="blur2" />
      <feMerge>
        <feMergeNode in="blur2" />
        <feMergeNode in="blur1" />
        <feMergeNode in="SourceGraphic" />
      </feMerge>
    </filter>
    <linearGradient id="badgeGrad" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="${accentColor}" stop-opacity="0.95" />
      <stop offset="100%" stop-color="#7928CA" stop-opacity="0.95" />
    </linearGradient>
  </defs>

  <!-- Top Kinetic Chapter/Pillar Banner -->
  <g transform="translate(140, 160)">
    <rect x="0" y="0" width="800" height="70" rx="35" fill="#000000" fill-opacity="0.65" stroke="url(#badgeGrad)" stroke-width="3" filter="url(#neonGlow)"/>
    <text x="400" y="46" font-family="Arial, Helvetica, sans-serif" font-size="30" font-weight="900" fill="#FFFFFF" text-anchor="middle" letter-spacing="3">
      ${cleanText.toUpperCase()}
    </text>
  </g>
</svg>`;
}

function main() {
  const params = parseArgs();
  const svgContent = generateNeonBadgeSVG(params.text, params.accent);
  
  const outPath = path.resolve(params.output);
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  fs.writeFileSync(outPath, svgContent, 'utf-8');
  console.log(`[KINETIC RENDERER] Generated vector badge -> ${outPath}`);
}

main();

