(function(root){
 'use strict';
 const geometryIcon=type=>/POINT/i.test(type)?'point':/LINE/i.test(type)?'line':/POLYGON/i.test(type)?'polygon':'table';
 const filterTables=(rows,query='',geometry='')=>rows.filter(t=>[t.key,t.title,t.table].join(' ').toLocaleLowerCase().includes(query.toLocaleLowerCase())&&(!geometry||String(t.geom_type||'').toLowerCase().includes(geometry)));
 function reorderLayers(rows,id,direction){const result=rows.slice(),index=result.findIndex(l=>l.id===id),next=index+direction;if(index>=0&&next>=0&&next<result.length)[result[index],result[next]]=[result[next],result[index]];return result;}
 root.LiveLayers={geometryIcon,filterTables,reorderLayers};
 if(typeof module!=='undefined')module.exports=root.LiveLayers;
})(typeof window!=='undefined'?window:globalThis);
