(function(root){
 'use strict';
 function authURL(value,origin){const url=new URL(value,origin);if(url.origin!==origin||!url.pathname.startsWith('/live/auth/'))throw Error('مسیر ورود معتبر نیست.');return url.href;}
 class LiveAuth {
  constructor({onSuccess,onError}){this.onSuccess=onSuccess;this.onError=onError;this.pending=null;}
  open(){if(this.pending)return this.pending;const trigger=document.activeElement;this.dialog=document.createElement('dialog');this.dialog.className='live-auth-dialog';this.dialog.setAttribute('aria-label','ورود دوباره به Live');const close=document.createElement('button');close.type='button';close.textContent='بستن';close.onclick=()=>this.dialog.close();this.body=document.createElement('div');this.dialog.append(close,this.body);document.body.append(this.dialog);this.dialog.showModal();this.pending=new Promise(resolve=>{this.dialog.onclose=()=>{this.dialog.remove();this.pending=null;trigger?.focus();resolve();};});this.load('/live/auth/login/?next='+encodeURIComponent(location.pathname)).catch(e=>this.onError(e.message));return this.pending;}
  async load(value,form){
   const url=authURL(value,location.origin),options={credentials:'same-origin',headers:{Accept:'text/html'}};
   if(form){options.method='POST';options.body=new FormData(form);}
   const response=await fetch(url,options);const text=await response.text();if(!response.ok)throw Error('دریافت فرم ورود ممکن نشد.');
   const doc=new DOMParser().parseFromString(text,'text/html'),content=doc.querySelector('[data-live-auth]');
   if(!content){const destination=new URL(response.url);if(!response.redirected||destination.origin!==location.origin||!destination.pathname.startsWith('/live/'))throw Error('پاسخ ورود معتبر نیست.');const token=doc.querySelector('[name=csrfmiddlewaretoken]')?.value;this.onSuccess(token);this.dialog.close();return;}
   this.body.replaceChildren(document.importNode(content,true));
   for(const script of this.body.querySelectorAll('script'))script.remove();
   for(const link of this.body.querySelectorAll('a[href]')){link.onclick=e=>{e.preventDefault();try{this.load(authURL(link.getAttribute('href'),location.origin)).catch(error=>this.showError(error));}catch(error){this.showError(error);}};}
   for(const item of this.body.querySelectorAll('form'))item.onsubmit=e=>{e.preventDefault();const action=item.getAttribute('action')||response.url;for(const b of item.querySelectorAll('button'))b.disabled=true;this.load(action,item).catch(error=>{this.showError(error);for(const b of item.querySelectorAll('button'))b.disabled=false;});};
   this.body.querySelector('input:not([type=hidden]),button')?.focus();
  }
  showError(error){let el=this.body.querySelector('[data-auth-error]');if(!el){el=document.createElement('p');el.dataset.authError='';el.setAttribute('role','alert');this.body.prepend(el);}el.textContent=error.message;}
 }
 root.LiveAuth=LiveAuth;if(typeof module!=='undefined')module.exports={authURL};
})(typeof window!=='undefined'?window:globalThis);
