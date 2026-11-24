import {defineAsyncComponent,type Component} from 'vue'
import WorkspaceSkeleton from './WorkspaceSkeleton.vue'
import WorkspaceLoadError from './WorkspaceLoadError.vue'
export function asyncWorkspace(loader:()=>Promise<{default:Component}>){
 return defineAsyncComponent({loader:async()=>(await loader()).default,loadingComponent:WorkspaceSkeleton,errorComponent:WorkspaceLoadError,delay:120,timeout:30000})
}
