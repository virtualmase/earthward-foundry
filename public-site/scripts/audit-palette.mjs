#!/usr/bin/env node
const palette = {
  'Mineral Paper': '#f1eee5',
  'Paper Shadow': '#dfdbcf',
  'Graphite': '#182c39',
  'Graphite Note': '#53656b',
  'Field Blue': '#173d59',
  'Iron Oxide': '#a64027',
  'Evidence Mint': '#c7d4cf',
  'Warm Signal': '#efac94',
  'Cool Signal': '#c1cdd3'
};
const pairs = [
  ['Graphite', 'Mineral Paper', 'primary reading'],
  ['Graphite Note', 'Mineral Paper', 'body notes'],
  ['Field Blue', 'Mineral Paper', 'public navigation and links'],
  ['Iron Oxide', 'Mineral Paper', 'decision and hold emphasis'],
  ['Mineral Paper', 'Field Blue', 'dark information field'],
  ['Warm Signal', 'Field Blue', 'hold label on dark field'],
  ['Cool Signal', 'Field Blue', 'supporting copy on dark field'],
  ['Graphite', 'Evidence Mint', 'closing reading field']
];
const linear = (channel) => {
  const value = parseInt(channel, 16) / 255;
  return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
};
const luminance = (hex) => {
  const channels = [hex.slice(1, 3), hex.slice(3, 5), hex.slice(5, 7)].map(linear);
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
};
const contrast = (first, second) => {
  const [light, dark] = [luminance(first), luminance(second)].sort((a, b) => b - a);
  return (light + 0.05) / (dark + 0.05);
};
let failed = false;
console.log('Earthward Foundry Workshop Ledger palette audit');
console.log('Role | Foreground | Background | Contrast | Status');
for (const [foreground, background, role] of pairs) {
  const ratio = contrast(palette[foreground], palette[background]);
  const threshold = role === 'body notes' || role.includes('supporting') ? 4.5 : 4.5;
  const status = ratio >= threshold ? 'PASS ≥ 4.5:1' : 'FAIL < 4.5:1';
  console.log(`${role} | ${foreground} | ${background} | ${ratio.toFixed(2)}:1 | ${status}`);
  if (ratio < threshold) failed = true;
}
if (failed) process.exit(1);
