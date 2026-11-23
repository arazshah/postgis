const {test}=require('node:test');const assert=require('node:assert/strict');
const {authURL}=require('../../../static/live/auth.js');
test('auth navigation accepts only same-origin Live auth URLs',()=>{const origin='https://live.postgis.ir';assert.equal(authURL('/live/auth/password/',origin),origin+'/live/auth/password/');for(const url of ['https://evil.test/live/auth/login/','/dashboard/','javascript:alert(1)','//evil.test/live/auth/login/'])assert.throws(()=>authURL(url,origin));});
