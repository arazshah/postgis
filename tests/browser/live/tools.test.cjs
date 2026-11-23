const {test}=require('node:test');const assert=require('node:assert/strict');const {initialValue,paramGroup}=require('../../../static/live/tools.js');
test('zero and false defaults are retained',()=>{assert.equal(initialValue({kind:'number',default:0}),0);assert.equal(initialValue({kind:'bool',default:false}),false);assert.equal(initialValue({kind:'bool',default:'true'}),true);});
test('explicit groups prevail and layer defaults to input',()=>{assert.equal(paramGroup({kind:'layer'}),'input');assert.equal(paramGroup({kind:'number',group:'advanced'}),'advanced');});
