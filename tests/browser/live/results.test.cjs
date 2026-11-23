const {test}=require('node:test');const assert=require('node:assert/strict');
const {LiveResults}=require('../../../static/live/results.js');
test('late table responses cannot replace newer page and jobs remain independent',()=>{const r=new LiveResults();const a=r.beginTable(),b=r.beginTable();assert.equal(r.acceptTable(a,'old'),false);assert.equal(r.acceptTable(b,'new'),true);r.setJob(7,{status:'running'});assert.equal(r.table,'new');assert.equal(r.jobs.get(7).status,'running');});
