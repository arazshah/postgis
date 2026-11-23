const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
test('Live prints a prepared map layout with a preserved map canvas', () => {
    const css = readFileSync('static/live/live.css', 'utf8');
    const js = readFileSync('static/live/live.js', 'utf8');
    assert.match(css, /@media print[\s\S]*\.ribbon[\s\S]*display:\s*none/);
    assert.match(js, /printable:\s*true/);
    assert.match(js, /showPrintPreview/);
});
