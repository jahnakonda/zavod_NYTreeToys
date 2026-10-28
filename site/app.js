// Сайт-прототип «Ёлочные игрушки: мастера и фабрики».
// Меню на мобильных, фильтр каталога, форма подписки (честная заглушка),
// появление блоков при скролле.

(function(){
  "use strict";

  // ―― Мобильное меню ――
  var burger=document.querySelector(".burger");
  var nav=document.querySelector(".nav");
  if(burger&&nav){
    burger.addEventListener("click",function(){
      var open=nav.classList.toggle("open");
      burger.setAttribute("aria-expanded",open?"true":"false");
    });
    nav.addEventListener("click",function(e){
      if(e.target.tagName==="A")nav.classList.remove("open");
    });
  }

  // ―― Фильтр каталога ――
  var chips=document.querySelectorAll(".chip");
  var cards=document.querySelectorAll(".fcard");
  var counter=document.querySelector(".chips-n");
  if(chips.length&&cards.length){
    chips.forEach(function(ch){
      ch.addEventListener("click",function(){
        chips.forEach(function(c){c.classList.remove("on")});
        ch.classList.add("on");
        var f=ch.getAttribute("data-f");
        var n=0;
        cards.forEach(function(c){
          var show=(f==="все"||c.getAttribute("data-t")===f);
          c.hidden=!show;
          if(show)n++;
        });
        if(counter)counter.textContent="Показано: "+n+" из "+cards.length;
      });
    });
  }

  // ―― Форма подписки: честная заглушка (бэкенд подключается позже) ――
  var form=document.querySelector(".subs form");
  var msg=document.querySelector(".subs-msg");
  if(form&&msg){
    form.addEventListener("submit",function(e){
      e.preventDefault();
      if(!form.checkValidity()){form.reportValidity();return;}
      msg.textContent="Спасибо! Автоподписка подключается на этапе бэкенда — пока проще подписаться в Telegram илиVK по кнопке выше.";
    });
  }

  // ―― Появление блоков при скролле ――
  var rv=document.querySelectorAll(".rv");
  if("IntersectionObserver" in window&&rv.length){
    var io=new IntersectionObserver(function(es){
      es.forEach(function(en){
        if(en.isIntersecting){en.target.classList.add("in");io.unobserve(en.target);}
      });
    },{threshold:.12});
    rv.forEach(function(el,i){
      el.style.transitionDelay=(i%4)*60+"ms";
      io.observe(el);
    });
  }else{
    rv.forEach(function(el){el.classList.add("in")});
  }
})();