(function(root){
 'use strict';
 root.LivePanels={
  open(element,trigger){element.classList.remove('hidden');element._liveTrigger=trigger||document.activeElement;},
  close(element){element.classList.add('hidden');element._liveTrigger?.focus();}
 };
})(window);
