/* Progressive enhancement: original selects remain the form's source of truth. */
(()=>{
 const valueProperty=Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value');
 const indexProperty=Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'selectedIndex');
 let opened=null,counter=0;
 const close=(restoreFocus=false)=>{
  if(!opened)return;const current=opened;opened=null;current.popup.remove();current.trigger.setAttribute('aria-expanded','false');current.trigger.removeAttribute('aria-activedescendant');if(restoreFocus)current.trigger.focus();
 };
 document.addEventListener('pointerdown',event=>{if(opened&&!opened.popup.contains(event.target)&&!opened.trigger.contains(event.target))close();});
 window.addEventListener('resize',()=>close());window.addEventListener('hashchange',()=>close());
 document.addEventListener('scroll',event=>{if(opened&&!opened.popup.contains(event.target))opened.reposition?.();},true);
 document.querySelectorAll('select:not([multiple])').forEach(select=>{
  const id='eg-choice-'+(++counter),wrapper=document.createElement('span'),trigger=document.createElement('button');
  wrapper.className='eg-select';trigger.type='button';trigger.className='eg-select-trigger';trigger.setAttribute('role','combobox');trigger.setAttribute('aria-haspopup','listbox');trigger.setAttribute('aria-expanded','false');trigger.setAttribute('aria-controls',id+'-list');trigger.dataset.selectId=select.id||select.name;
  const value=document.createElement('span');value.id=id+'-value';value.className='eg-select-value';trigger.append(value);
  const label=select.closest('label')?.querySelector('.eg-field-label');
  if(label){if(!label.id)label.id=id+'-label';trigger.setAttribute('aria-labelledby',label.id+' '+value.id);}
  else trigger.setAttribute('aria-label',select.getAttribute('aria-label')||select.name||'Выбрать значение');
  select.before(wrapper);wrapper.append(select,trigger);select.classList.add('eg-native-select');select.setAttribute('aria-hidden','true');select.tabIndex=-1;
  function sync(){
   value.textContent=select.selectedOptions[0]?.textContent||'Выбрать';trigger.disabled=select.disabled;trigger.title=value.textContent;
   if(opened?.select===select)close();
  }
  // Existing form code updates .value directly (profile loading / readonly mode).
  Object.defineProperty(select,'value',{configurable:true,get(){return valueProperty.get.call(this)},set(next){valueProperty.set.call(this,next);sync();}});
  Object.defineProperty(select,'selectedIndex',{configurable:true,get(){return indexProperty.get.call(this)},set(next){indexProperty.set.call(this,next);sync();}});
  select.addEventListener('change',sync);select.addEventListener('focus',()=>trigger.focus());
  select.form?.addEventListener('reset',()=>requestAnimationFrame(sync));
  new MutationObserver(sync).observe(select,{attributes:true,childList:true,subtree:true,attributeFilter:['disabled','selected','label']});
  function open(){
   if(trigger.disabled)return;close();trigger.focus({preventScroll:true});
   const popup=document.createElement('div');popup.id=id+'-list';popup.className='eg-select-menu';popup.setAttribute('role','listbox');popup.setAttribute('aria-label',label?.textContent||trigger.getAttribute('aria-label')||'Варианты');
   const options=[...select.options].filter(option=>!option.hidden);const enabled=options.map((o,i)=>!o.disabled&&!o.parentElement?.disabled?i:-1).filter(i=>i>=0);
   let active=options.indexOf(select.selectedOptions[0]);if(!enabled.includes(active))active=enabled[0]??-1;
   const nodes=options.map((option,index)=>{
    const item=document.createElement('div');item.id=id+'-option-'+index;item.className='eg-select-option';item.setAttribute('role','option');item.setAttribute('aria-selected',String(option.selected));item.setAttribute('aria-disabled',String(!enabled.includes(index)));item.textContent=option.textContent;
    item.addEventListener('pointerdown',event=>event.preventDefault());
    item.addEventListener('pointermove',()=>{if(enabled.includes(index))highlight(index,false);});item.addEventListener('click',()=>commit(index));popup.append(item);return item;
   });
   const current={select,trigger,popup,move,commit:()=>commit(active),highlight};opened=current;document.body.append(popup);
   current.reposition=()=>{
    const rect=trigger.getBoundingClientRect();if(!rect.height||rect.bottom<0||rect.top>innerHeight){close();return;}
    const width=Math.min(rect.width,innerWidth-24);popup.style.width=width+'px';popup.style.left=Math.min(Math.max(12,rect.left),innerWidth-width-12)+'px';
    const below=innerHeight-rect.bottom-12,above=rect.top-12,wanted=Math.min(320,popup.scrollHeight+2),placeAbove=below<Math.min(wanted,160)&&above>below;
    popup.style.maxHeight=Math.max(64,Math.min(320,placeAbove?above-6:below-6))+'px';popup.style.top='auto';popup.style.bottom='auto';
    if(placeAbove)popup.style.bottom=(innerHeight-rect.top+6)+'px';else popup.style.top=(rect.bottom+6)+'px';
   };current.reposition();
   trigger.setAttribute('aria-expanded','true');highlight(active,true);
   function highlight(index,scroll){active=index;nodes.forEach((node,i)=>node.classList.toggle('is-active',i===index));if(index>=0){trigger.setAttribute('aria-activedescendant',nodes[index].id);if(scroll)nodes[index].scrollIntoView({block:'nearest'});}}
   function move(direction){if(!enabled.length)return;const position=enabled.indexOf(active);highlight(enabled[Math.max(0,Math.min(enabled.length-1,position+direction))],true);}
   function commit(index){
    if(opened!==current||!enabled.includes(index))return;
    const next=options[index].value,changed=select.value!==next;close();select.value=next;trigger.focus();
    if(changed){select.dispatchEvent(new Event('input',{bubbles:true}));select.dispatchEvent(new Event('change',{bubbles:true}));}
   }
   current.first=()=>highlight(enabled[0]??-1,true);current.last=()=>highlight(enabled.at(-1)??-1,true);
   current.search=text=>{const index=enabled.find(i=>options[i].textContent.trim().toLocaleLowerCase('ru-RU').startsWith(text));if(index!==undefined)highlight(index,true);};
  }
  trigger.addEventListener('click',event=>{event.preventDefault();if(opened?.select===select)close();else open();});
  let search='',searchAt=0;
  trigger.addEventListener('keydown',event=>{
   if(event.key==='Tab'){close();return;}
   if(event.key==='Escape'){if(opened?.select===select){event.preventDefault();close(true);}return;}
   if(['ArrowDown','ArrowUp','Home','End','Enter',' '].includes(event.key)){
    event.preventDefault();const wasOpen=opened?.select===select;if(!wasOpen)open();else if(event.key==='Enter'||event.key===' '){opened.commit();return;}
    if(opened?.select!==select)return;
    if(event.key==='Home')opened.first();else if(event.key==='End')opened.last();else if(wasOpen&&event.key==='ArrowDown')opened.move(1);else if(wasOpen&&event.key==='ArrowUp')opened.move(-1);return;
   }
   if(event.key.length===1&&!event.ctrlKey&&!event.metaKey&&!event.altKey){
    event.preventDefault();if(opened?.select!==select)open();const now=Date.now();search=now-searchAt<700?search+event.key:event.key;searchAt=now;opened?.search(search.toLocaleLowerCase('ru-RU'));
   }
  });
  sync();
 });
})();
