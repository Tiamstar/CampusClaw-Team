import {onUnmounted,ref} from 'vue'
export type ToastLevel='success'|'warning'|'error'|'info'
export function useToasts(){
 const toasts=ref<{id:number;text:string;level:ToastLevel}[]>([])
 const timers=new Map<number,ReturnType<typeof setTimeout>>()
 let sequence=0
 function dismiss(id:number){clearTimeout(timers.get(id));timers.delete(id);toasts.value=toasts.value.filter(t=>t.id!==id)}
 function notify(text:string,level:ToastLevel='info',duration?:number){
  if(!text.trim())return
  const duplicate=toasts.value.find(t=>t.text===text&&t.level===level)
  if(duplicate)dismiss(duplicate.id)
  const id=++sequence
  toasts.value.push({id,text,level})
  // Keep concurrent notices readable and bounded. Errors remain until dismissed.
  if(toasts.value.length>5)dismiss(toasts.value[0].id)
  if(level!=='error')timers.set(id,setTimeout(()=>dismiss(id),duration??(level==='success'?4000:7000)))
 }
 onUnmounted(()=>{timers.forEach(clearTimeout);timers.clear()})
 return {toasts,notify,dismiss}
}
