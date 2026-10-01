export async function api<T>(url:string, init:RequestInit={}):Promise<T>{
  const response=await fetch(url,{...init,headers:{...(init.body instanceof FormData?{}:{'Content-Type':'application/json'}),...init.headers}});
  if(!response.ok){let detail;try{const body=await response.json();detail=typeof body.detail==='string'?body.detail:JSON.stringify(body.detail);}catch{detail=response.statusText;}
    throw new Error(detail || `Request failed (${response.status})`);}
  return response.json() as Promise<T>;
}
