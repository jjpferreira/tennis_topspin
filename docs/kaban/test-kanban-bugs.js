#!/usr/bin/env node
/**
 * Quick test: load features.json and verify BUG column gets 2 cards.
 * Run from _docs/product/kaban/: node test-kanban-bugs.js
 */
const fs = require('fs');
const path = require('path');

const jsonPath = path.join(__dirname, 'features.json');
const data = JSON.parse(fs.readFileSync(jsonPath, 'utf8'));
const features = data.features || [];

const COLUMNS = ['IDEA', 'BUG', 'PLANNED', 'IN-PROGRESS', 'COMPLETED', 'CANCELLED', 'REMOVED'];
const byStatus = {};
COLUMNS.forEach(c => { byStatus[c] = []; });

features.forEach(f => {
  const status = (f.status || 'IDEA').toUpperCase().replace(/\s+/g, '-');
  if (byStatus[status]) byStatus[status].push(f);
  else byStatus['IDEA'].push(f);
});

const bugCount = (byStatus['BUG'] || []).length;
console.log('BUG column card count:', bugCount);
console.log('BUG cards:', (byStatus['BUG'] || []).map(f => f.featureId + ' ' + (f.title || '').slice(0, 50)));

if (bugCount !== 2) {
  console.error('FAIL: expected 2 bugs in BUG column, got', bugCount);
  process.exit(1);
}
console.log('OK: 2 bugs in BUG column');
process.exit(0);
