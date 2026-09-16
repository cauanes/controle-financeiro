import {useEffect, useState} from 'react';
import {api} from './api';
export function useData<T>(path: string, revision = 0) {
  const [data,setData] = useState<T|null>(null), [error,setError] = useState(''), [loading,setLoading] = useState(true);
  useEffect(() => { const controller = new AbortController(); setLoading(true); setData(null); setError('');
    api<T>(path,'GET',undefined,controller.signal).then(setData).catch(e=>{if(e.name!=='AbortError')setError(e.message);}).finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return ()=>controller.abort();
  },[path,revision]);
  return {data,error,loading};
}
