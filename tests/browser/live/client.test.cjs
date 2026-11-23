const {test}=require('node:test');
const assert=require('node:assert/strict');
const {LiveClient}=require('../../../static/live/client.js');
test('expired session is a typed error, not a JSON parse failure',async()=>{
 const client=new LiveClient({fetch:async()=>({status:401,ok:false,headers:new Headers({'content-type':'application/json'}),json:async()=>({error:{code:'auth_required',message:'ورود لازم است'}})})});
 await assert.rejects(()=>client.request('/live/'),e=>e.code==='auth_required');
});
test('HTML redirect from old endpoints is reported as authentication required',async()=>{
 const client=new LiveClient({fetch:async()=>({status:200,ok:true,redirected:true,headers:new Headers({'content-type':'text/html'})})});
 await assert.rejects(()=>client.request('/live/'),e=>e.code==='auth_required');
});
test('structured errors retain field validation',async()=>{
 const client=new LiveClient({fetch:async()=>({status:400,ok:false,headers:new Headers({'content-type':'application/json'}),json:async()=>({error:{code:'invalid',message:'نام نامعتبر',fields:{title:'لازم است'}}})})});
 await assert.rejects(()=>client.request('/live/'),e=>e.fields.title==='لازم است');
});
