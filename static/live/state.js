/* Revision-based save tracking, shared by the Live panels. */
(function(root){
 'use strict';
 class LiveState {
  constructor(){this.revision=0;this.savedRevision=0;this.table={};this.jobs=new Map();}
  get dirty(){return this.revision!==this.savedRevision;}
  markDirty(){return ++this.revision;}
  markSaved(revision){this.savedRevision=Math.max(this.savedRevision,Math.min(revision,this.revision));}
 }
 root.LiveState=LiveState;
 if(typeof module!=='undefined')module.exports={LiveState};
})(typeof window!=='undefined'?window:globalThis);
