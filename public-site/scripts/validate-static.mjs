#!/usr/bin/env node
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const read = (file) => readFileSync(resolve(root, file), 'utf8');
const fail = (message) => { console.error(`FAIL: ${message}`); process.exitCode = 1; };
const requiredFiles = ['index.html','404.html','site.css','favicon.svg','og-image.svg','manifest.webmanifest','robots.txt','sitemap.xml','llms.txt','README.md','QA.md'];
for (const file of requiredFiles) if (!existsSync(resolve(root, file))) fail(`missing ${file}`);
const html = read('index.html'); const css = read('site.css'); const errorPage = read('404.html'); const sitemap = read('sitemap.xml'); const robots = read('robots.txt'); const manifest = read('manifest.webmanifest'); const llms = read('llms.txt');
const mustContain = (body, value, label) => { if (!body.includes(value)) fail(`${label} missing: ${value}`); };
for (const value of ['<main id="main">','<header class="site-header"','<footer class="site-footer"','<h1 id="hero-title">','<h2 id="loop-title">','<h2 id="boundary-title">','<h2 id="basis-title">','<script type="application/ld+json">','https://virtualmase.github.io/earthward-foundry/','PUBLIC BOUNDARY / 01','HUMAN-ONLY','NOT CLAIMED','https://github.com/virtualmase/earthward-foundry/issues']) mustContain(html,value,'index.html');
for (const value of ['rel="canonical"','og:image','twitter:card','favicon.svg','manifest.webmanifest','SoftwareSourceCode','WebSite','WebPage']) mustContain(html,value,'metadata');
for (const value of ['https://virtualmase.github.io/earthward-foundry/']) mustContain(sitemap,value,'sitemap');
mustContain(robots,'Sitemap: https://virtualmase.github.io/earthward-foundry/sitemap.xml','robots');
for (const value of ['"start_url": "/earthward-foundry/"','favicon.svg']) mustContain(manifest,value,'manifest');
for (const value of ['Public Field Guide','Important limits','not a public API']) mustContain(llms,value,'llms.txt');
for (const value of ['href="./"','noindex,follow']) mustContain(errorPage,value,'404.html');
for (const value of ['.skip-link','a:focus-visible','@media(max-width:680px)','@media(prefers-reduced-motion:reduce)']) mustContain(css,value,'site.css');
for (const phrase of ['certified quality','guaranteed quality','certification service','public API is available','proven customer results','self-certifies','automated acceptance']) if (html.toLowerCase().includes(phrase)) fail(`unsupported public claim: ${phrase}`);
for (const pattern of [/\b(fetch|XMLHttpRequest|sendBeacon|localStorage|sessionStorage|document\.cookie)\b/,/googletagmanager|google-analytics|analytics\.js|hotjar|segment\.com/i,/<form\b/i,/script\s+src=/i]) if (pattern.test(html)) fail(`prohibited runtime pattern: ${pattern}`);
for (const path of ['/services/','gce_install.sh','127.0.0.1:5000','127.0.0.1:5001','ALLOW_UNAUTHENTICATED','API_KEY','bearer ']) if (html.toLowerCase().includes(path.toLowerCase())) fail(`protected pilot detail exposed: ${path}`);
if (process.exitCode) process.exit(process.exitCode);
console.log('PASS: Earthward Foundry public field guide contains required static routes, reader boundary, metadata, accessibility controls, and protected-pilot exclusions.');
