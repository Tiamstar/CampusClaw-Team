import http from 'k6/http';
import {check,sleep} from 'k6';
import {Counter} from 'k6/metrics';
const fixture=JSON.parse(open(__ENV.FIXTURE||'/private/fixture.json'));
const target=__ENV.TARGET||'search';
const created=new Counter('submissions_created');
const replayed=new Counter('submissions_replayed');
export const options={vus:Number(__ENV.VUS||20),duration:__ENV.DURATION||'60s',
  thresholds:{http_req_failed:['rate<0.01'],checks:['rate>0.99']},
  summaryTrendStats:['avg','med','p(90)','p(95)','p(99)','max']};
const base=__ENV.BASE_URL||'http://backend:8000/api/';
export default function(){
  const params={headers:{Authorization:`Bearer ${fixture.token}`,'Content-Type':'application/json'},tags:{endpoint:target}};
  let response;
  if(target==='submit'){
    const body=JSON.stringify({text_content:'合成性能验收：积分结果1；不评分。',submission_key:`bench-${__ENV.RUN_ID}-${__VU}-${__ITER}`});
    response=http.post(`${base}assignments/${fixture.submit_assignment_id}/submit/`,body,params);
    created.add(response.status===201?1:0);
    check(response,{'new submission persisted':r=>r.status===201&&r.json('id')>0});
    // Replay exactly the same receipt key: measure consistency separately from new acceptance.
    const again=http.post(`${base}assignments/${fixture.submit_assignment_id}/submit/`,body,{...params,tags:{endpoint:'submit_replay'}});
    replayed.add(again.status===200?1:0);
    check(again,{'same key returns same version':r=>r.status===200&&r.json('id')===response.json('id')});
  }else if(target==='query'){
    response=http.get(`${base}assignments/${fixture.query_assignment_id}/`,params);
    check(response,{'fixed history remains twenty versions':r=>r.status===200&&r.json('my_versions').length===20});
  }else{
    response=http.get(`${base}courses/${fixture.course_id}/knowledge/search/?mode=keyword&q=${encodeURIComponent(fixture.query)}`,params);
    check(response,{'actual keyword hit in selected course':r=>r.status===200&&r.json('hits').length===1&&r.json('hits')[0].excerpt.includes('benchmarkneedle')});
  }
  sleep(Number(__ENV.THINK_SECONDS||1));
}
export function handleSummary(data){
  return {[`/results/${__ENV.RUN_ID}-${target}.json`]:JSON.stringify({label:__ENV.RUN_ID,target,fixture:{course_id:fixture.course_id,
    query_assignment_id:fixture.query_assignment_id,submit_assignment_id:fixture.submit_assignment_id},vus:options.vus,
    duration:options.duration,think_seconds:Number(__ENV.THINK_SECONDS||1),...data},null,2)};
}
