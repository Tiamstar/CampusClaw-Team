// @vitest-environment jsdom
import {it,expect,vi} from 'vitest'
import {api,ApiError} from '../src/api'
import {authenticatedFetch} from '../src/auth'
vi.mock('../src/auth',()=>({authenticatedFetch:vi.fn()}))
it('preserves safe HTTP status without exposing server error bodies',async()=>{
 vi.mocked(authenticatedFetch).mockResolvedValueOnce(new Response(JSON.stringify({error:'无权访问'}),{status:403}))
 await expect(api('private/')).rejects.toMatchObject({name:'ApiError',status:403,message:'无权访问'})
 vi.mocked(authenticatedFetch).mockResolvedValueOnce(new Response('secret traceback',{status:500}))
 try{await api('private/');throw new Error('expected failure')}catch(e){expect(e).toBeInstanceOf(ApiError);expect((e as ApiError).status).toBe(500);expect((e as Error).message).not.toContain('secret')}
})
