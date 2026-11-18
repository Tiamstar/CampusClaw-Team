export type LatencyPoint={time:string;samples:number;avg_ms:number|null;p95_ms:number|null}
export type HttpRoute={route:string;method:string;streaming:boolean;requests:number;completed:number;closed:number;transport_errors:number;client_errors:number;server_errors:number;avg_ms:number|null;p95_ms:number|null}
export type HttpLatency={routes:HttpRoute[];curve:(LatencyPoint&{route:string;method:string;streaming:boolean;requests:number})[];routes_truncated:boolean;interval:string;note:string}
export type DurationCurves={model:(LatencyPoint&{skill_id:string})[];task:(LatencyPoint&{skill_id:string;processing_samples:number;processing_avg_ms:number|null;processing_p95_ms:number|null;queue_avg_ms:number|null;queue_p95_ms:number|null})[];interval:string;note:string}
