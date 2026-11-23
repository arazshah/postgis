const {test}=require('node:test');
const assert=require('node:assert/strict');
const {LiveState}=require('../../../static/live/state.js');
test('a slow save does not mark newer edits as saved',()=>{
 const state=new LiveState(); state.markDirty(); const saved=state.revision;
 state.markDirty(); state.markSaved(saved); assert.equal(state.dirty,true);
 state.markSaved(state.revision); assert.equal(state.dirty,false);
});
test('table and jobs have independent state',()=>{
 const state=new LiveState(); state.table={page:2}; state.jobs.set(1,{status:'running'});
 assert.equal(state.table.page,2); assert.equal(state.jobs.get(1).status,'running');
});
