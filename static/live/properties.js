(function(root){
 'use strict';
 class LayerDraft {
  constructor(layer){this.layer=layer;this.cancel();}
  cancel(){this.title=this.layer.title;this.style=structuredClone(this.layer.style);}
  apply(){this.layer.title=this.title;this.layer.style=structuredClone(this.style);}
 }
 root.LayerDraft=LayerDraft;
 if(typeof module!=='undefined')module.exports={LayerDraft};
})(typeof window!=='undefined'?window:globalThis);
