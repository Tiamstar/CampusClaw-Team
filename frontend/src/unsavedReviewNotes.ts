// Functions only: private note contents never leave their owning component.
const pending=new Map<()=>boolean,string>()
export function registerReviewNotes(check:()=>boolean,message='复习备注尚未保存，离开会丢失修改。确定继续？'){
  pending.set(check,message)
  return ()=>pending.delete(check)
}
export function hasUnsavedReviewNotes(){return [...pending.keys()].some(check=>check())}
export function confirmReviewNotesLeave(){
  const entry=[...pending].find(([check])=>check())
  return !entry||window.confirm(entry[1])
}
