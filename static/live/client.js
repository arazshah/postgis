(function(root){
 'use strict';
 class LiveRequestError extends Error {
  constructor(message,code,fields={}){super(message);this.code=code;this.fields=fields;}
 }
 class LiveClient {
  constructor(options={}){this.fetch=options.fetch||root.fetch.bind(root);this.csrf=options.csrf||'';}
  async request(url,{method='GET',body,signal}={}){
   const headers={Accept:'application/json'};
   if(method!=='GET'&&method!=='HEAD')headers['X-CSRFToken']=this.csrf;
   if(body&&!(body instanceof FormData)){headers['Content-Type']='application/json';body=JSON.stringify(body);}
   const response=await this.fetch(url,{method,body,signal,headers,credentials:'same-origin'});
   if(response.status===401)throw new LiveRequestError('برای ادامه دوباره وارد شوید.','auth_required');
   const json=response.headers.get('content-type')?.includes('application/json');
   if(!json)throw new LiveRequestError(response.redirected?'برای ادامه دوباره وارد شوید.':'پاسخ سرور قابل خواندن نیست.',response.redirected?'auth_required':'invalid_response');
   const data=await response.json();
   if(!response.ok){const error=data.error;throw new LiveRequestError(typeof error==='string'?error:error?.message||'عملیات ممکن نشد.',error?.code||'request_failed',error?.fields);}
   return data;
  }
 }
 root.LiveClient=LiveClient;root.LiveRequestError=LiveRequestError;
 if(typeof module!=='undefined')module.exports={LiveClient,LiveRequestError};
})(typeof window!=='undefined'?window:globalThis);
