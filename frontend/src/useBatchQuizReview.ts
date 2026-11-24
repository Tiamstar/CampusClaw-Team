import {ref} from 'vue'
import {api,streamAgent} from './api'
type Suggestion={question_id:number;score:string|null;feedback:string;needs_reference:boolean}
type Review={ready:boolean;revision:number;items:Suggestion[];status:string;error:string}
export function useBatchQuizReview(){
 const busy=ref(false),stop=ref(false),progress=ref(''),reviews=ref<Record<number,Review>>({})
 async function run(rows:{attempt_id:number;grade_revision:number}[]){
  if(busy.value)return
  busy.value=true;stop.value=false
  const targets=rows.slice(0,20).map(r=>({attempt_id:r.attempt_id,grade_revision:r.grade_revision}))
  let completed=0
  try{
   for(const row of targets){
    if(stop.value)break
    const id=row.attempt_id
    reviews.value[id]={ready:false,revision:row.grade_revision,items:[],status:'正在准备',error:''}
    const current=reviews.value[id]!
    progress.value=`正在处理 ${completed+1} / ${targets.length} 份答卷`
    try{
     const history=await api<{status:string;body:string}[]>(`quiz-attempts/${id}/suggestion/`)
     for(const old of history){
      if(old.status!=='awaiting_review')continue
      try{const parsed=JSON.parse(old.body);if(parsed.answer_encoding_version===2&&parsed.grade_revision===row.grade_revision&&Array.isArray(parsed.items)){current.items=parsed.items;current.ready=true;current.status='已恢复建议，请逐题复核';break}}catch{}
     }
     if(!current.items.length){
      if(stop.value){current.status='已停止，尚未启动模型';break}
      let done=false
      await streamAgent(`quiz-attempts/${id}/suggestion/`,{stream:true},{onEvent:(type,payload)=>{
       if(type==='status')current.status=payload.text
       if(type==='item')current.status=`已分析 ${Number(current.items.length)+1} 题（完成后可采用）`
       if(type==='item')current.items.push(payload)
       if(type==='complete'){
        if(payload.grade_revision!==row.grade_revision){current.error='评分版本已变化，请刷新后重新评阅';return}
        current.items=payload.items;current.status='评阅完成，请逐题复核';done=true
       }
       if(type==='error')current.error=payload.error
      }})
      if(current.error)throw new Error(current.error)
      if(!done)throw new Error('连接中断，请重试；正式成绩未改变')
      current.ready=true
     }
    }catch(e){current.ready=false;current.items=[];current.error=e instanceof Error?e.message:'评阅失败，请重试';current.status='未完成'}
    completed++
   }
   progress.value=`本轮已处理 ${completed} / ${targets.length} 份${stop.value?'，已停止后续评阅':''}；请逐题核对建议，正式成绩未改变。`
  }finally{busy.value=false}
 }
 return {busy,progress,reviews,run,stopAfterCurrent:()=>{stop.value=true}}
}
