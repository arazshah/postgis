(function(root){
 'use strict';
 const initialValue=p=>p.kind==='bool'?[true,'true','1','on',1].includes(p.default):(p.default??'');
 const paramGroup=p=>p.group||(p.kind==='layer'?'input':'settings');
 root.LiveTools={initialValue,paramGroup};
 if(typeof module!=='undefined')module.exports=root.LiveTools;
})(typeof window!=='undefined'?window:globalThis);
