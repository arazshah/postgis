(function(root){
 'use strict';
 class LiveResults {
  constructor(){this.generation=0;this.table='';this.jobs=new Map();}
  beginTable(){return ++this.generation;}
  acceptTable(generation,value){if(generation!==this.generation)return false;this.table=value;return true;}
  setJob(id,value){this.jobs.set(id,value);}
 }
 root.LiveResults=LiveResults;
 if(typeof module!=='undefined')module.exports={LiveResults};
})(typeof window!=='undefined'?window:globalThis);
