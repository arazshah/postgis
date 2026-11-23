(function(root){
 'use strict';
 const groups={
  پروژه:{'باز کردن پروژه':'layers','ذخیره':'save'},
  پیمایش:{'نمای کامل':'expand','بزرگ‌نمایی':'plus','کوچک‌نمایی':'minus'},
  لایه:{'ویژگی لایه':'settings','نقشه پایه':'globe','افزودن لایه':'layers','سبک لایه':'edit'},
  داده:{'ورود فایل':'upload','جدول توصیفی':'table','مدیریت جدول':'db','ویرایش داده':'edit'},
  پردازش:{'حریم (Buffer)':'target','مجاورت':'target','همپوشانی':'compare','هندسه':'polygon','آمار مکانی':'chart','شبکه':'link','همه ابزارها':'settings'},
  تصاویر:{'تصاویر ماهواره‌ای':'satellite'},
  هوشمند:{'پرسش فارسی':'spark'},
  انتشار:{'Vector Tile':'layers','WMS / WFS':'globe','REST API':'code','خروجی QGIS':'download'},
  خروجی:{'چاپ و گزارش':'print'},
  قابلیت‌ها:{'بازارچه':'cube','برداشت میدانی':'point'}
 };
 const LiveCommands={};for(const [group,items]of Object.entries(groups))for(const [label,icon]of Object.entries(items))LiveCommands[label]={label,icon,group};
 root.LiveCommands=Object.freeze(LiveCommands);
 if(typeof module!=='undefined')module.exports={LiveCommands};
})(typeof window!=='undefined'?window:globalThis);
