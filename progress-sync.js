import {firebaseConfig} from './firebase-config.js';
import {initializeApp} from 'https://www.gstatic.com/firebasejs/12.12.0/firebase-app.js';
import {
  getAuth, GoogleAuthProvider, onAuthStateChanged, signInWithPopup, signOut
} from 'https://www.gstatic.com/firebasejs/12.12.0/firebase-auth.js';
import {
  collection, doc, getFirestore, onSnapshot, runTransaction
} from 'https://www.gstatic.com/firebasejs/12.12.0/firebase-firestore.js';

if (firebaseConfig) startProgressSync();

function startProgressSync() {
  const {words, read, show} = window.cet6Progress;
  const button = document.getElementById('sync-button');
  const status = document.getElementById('sync-status');
  const logout = document.getElementById('sync-logout');
  const app = initializeApp(firebaseConfig);
  const auth = getAuth(app);
  auth.languageCode = 'zh-CN';
  const db = getFirestore(app);
  const provider = new GoogleAuthProvider();
  provider.setCustomParameters({prompt:'select_account'});
  const key = 'cet6_progress_sync_v1';
  const guest = () => read(null);
  const indexes = new Map(words.map((word,i)=>[word,i]));
  let session = null;
  let lastTime = 0;

  function stored(name,fallback) {
    try {return JSON.parse(localStorage.getItem(name)) ?? fallback;}
    catch {return fallback;}
  }
  function persist(name,value) {
    try {localStorage.setItem(name,JSON.stringify(value));return true;}
    catch {return false;}
  }
  function wordState(value = {}) {
    return {
      em:value.em===true,
      zm:value.zm===true,
      n:Number.isSafeInteger(value.n)?Math.min(1_000_000,Math.max(0,value.n)):0
    };
  }
  function note(text) {status.textContent=text;}
  function redraw(connection,ids) {
    if (session!==connection) return;
    const next = {};
    const saved = read(connection.uid);
    for (const id of ids) {
      const index = indexes.get(id);
      if (index===undefined || connection.pending.has(id)) continue;
      const value = connection.remote.get(id);
      if (value) next[index] = wordState(value);
      else if (Object.hasOwn(saved,index)) next[index] = wordState();
    }
    show(connection.uid,next);
  }
  function rememberOperation(connection,changes) {
    const time = lastTime = Math.max(Date.now(),lastTime+1);
    const id = String(time).padStart(16,'0')+'_'+crypto.randomUUID();
    const path = connection.queuePrefix+id;
    const entry = {id,path,changes};
    connection.queue.set(id,entry);
    for (const change of changes) {
      connection.pending.set(change.word,(connection.pending.get(change.word)||0)+1);
    }
    if (!persist(path,changes)) connection.storageError=true;
  }
  function enqueueImport(connection) {
    if (stored(connection.importKey,false)) return;
    let changes = [];
    for (const [index,value] of Object.entries(guest())) {
      const word = words[index];
      if (!word) continue;
      const initial = wordState(value);
      if (!initial.em && !initial.zm && !initial.n) continue;
      changes.push({word,initial});
      if (changes.length===40) {
        rememberOperation(connection,changes);
        changes=[];
      }
    }
    if (changes.length) rememberOperation(connection,changes);
    if (!connection.storageError && !persist(connection.importKey,true)) connection.storageError=true;
  }
  function setState(connection,word,value) {
    const old = connection.remote.get(word);
    if (!old || value.rev>=old.rev) connection.remote.set(word,value);
  }
  function displayStatus(connection) {
    if (session!==connection) return;
    if (connection.storageError) {
      note('浏览器无法持久保存待同步修改，请保持页面打开。');
    } else if (!navigator.onLine) {
      note('离线，修改已保存在本机。');
    } else if (connection.denied) {
      note('此 Google 账号没有同步权限。');
    } else if (connection.error) {
      note('暂时无法连接云端，已保留待同步修改。');
    } else if (connection.queue.size || !connection.online) {
      note('正在同步…');
    } else {
      note('进度已同步');
    }
  }
  function valueForOperation(previous,change) {
    const value={...previous};
    if (change.initial) {
      let changed=false;
      for (const field of ['em','zm','n']) {
        if (change.initial[field] && !Object.hasOwn(value,field)) {
          value[field]=change.initial[field];
          changed=true;
        }
      }
      return changed ? value : null;
    }
    if (change.field==='n') value.n=Math.min(1_000_000,Math.max(0,wordState(previous).n+change.value));
    else value[change.field]=change.value;
    return value;
  }
  function commitOperation(connection,operation) {
    const receipt=doc(db,'vocabProgress',connection.uid,'receipts',operation.id);
    const changes=operation.changes.map(change=>({
      ...change,ref:doc(connection.words,'w_'+encodeURIComponent(change.word))
    }));
    return runTransaction(db,async transaction=>{
      const [done,...snapshots]=await Promise.all([
        transaction.get(receipt),...changes.map(change=>transaction.get(change.ref))
      ]);
      const result=new Map();
      for (const [index,change] of changes.entries()) {
        const previous=snapshots[index].data();
        const value=done.exists()?null:valueForOperation(previous,change);
        if (value) {
          value.rev=(previous?.rev||0)+1;
          transaction.set(change.ref,{...value,word:change.word});
          result.set(change.word,value);
        } else if (previous) result.set(change.word,previous);
      }
      if (!done.exists()) transaction.set(receipt,{applied:true});
      return result;
    });
  }
  async function drain(connection) {
    if (session!==connection || connection.busy || connection.denied || !navigator.onLine) return;
    connection.busy=true;
    displayStatus(connection);
    try {
      while (session===connection && connection.queue.size && navigator.onLine) {
        const id=[...connection.queue.keys()].sort()[0];
        const operation=connection.queue.get(id);
        const applied=await commitOperation(connection,operation);
        if (session!==connection) return;
        for (const [word,value] of applied) setState(connection,word,value);
        const touched=[];
        for (const {word} of operation.changes) {
          const count=connection.pending.get(word)-1;
          if (count>0) connection.pending.set(word,count);
          else connection.pending.delete(word);
          touched.push(word);
        }
        connection.queue.delete(id);
        try {localStorage.removeItem(operation.path);} catch {}
        connection.error=false;
        redraw(connection,touched);
      }
    } catch (error) {
      connection.error=true;
      connection.denied=error.code==='permission-denied';
      console.warn('CET-6 progress write:',error.code||error.message);
    } finally {
      connection.busy=false;
      displayStatus(connection);
    }
  }
  function connect(user) {
    session?.unsubscribe?.();
    session=null;
    button.disabled=false;
    if (!user) {
      show(null);
      button.textContent='登录同步';
      logout.hidden=true;
      note('');
      return;
    }
    const cache=read(user.uid);
    const connection={
      uid:user.uid,words:collection(db,'vocabProgress',user.uid,'words'),
      queuePrefix:key+':'+user.uid+':op:',importKey:key+':'+user.uid+':imported',
      remote:new Map(),pending:new Map(),queue:new Map(),
      busy:false,online:false,error:false,storageError:false
    };
    session=connection;
    try {
      for (let n=0;n<localStorage.length;n++) {
        const path=localStorage.key(n);
        if (!path?.startsWith(connection.queuePrefix)) continue;
        const changes=stored(path,[]);
        if (!Array.isArray(changes)||!changes.length) continue;
        const id=path.slice(connection.queuePrefix.length);
        lastTime=Math.max(lastTime,Number(id.split('_')[0])||0);
        connection.queue.set(id,{id,path,changes});
        for (const {word} of changes) connection.pending.set(word,(connection.pending.get(word)||0)+1);
      }
    } catch {connection.storageError=true;}
    show(user.uid);
    if (!stored(connection.importKey,false)) {
      const starting={...guest(),...cache};
      show(user.uid,starting);
      enqueueImport(connection);
    }
    button.textContent='同步状态';
    logout.hidden=false;
    connection.unsubscribe=onSnapshot(connection.words,{includeMetadataChanges:true},snapshot=>{
      if (session!==connection) return;
      const changed=[];
      for (const update of snapshot.docChanges()) {
        const value=update.doc.data();
        if (update.type==='removed') continue;
        setState(connection,value.word,value);
        changed.push(value.word);
      }
      connection.online=!snapshot.metadata.fromCache;
      redraw(connection,changed);
      displayStatus(connection);
      drain(connection);
    },error=>{
      if (session!==connection) return;
      connection.error=true;
      connection.denied=error.code==='permission-denied';
      note(connection.denied?'此 Google 账号没有同步权限。':'读取云端进度失败，本机记录仍可使用。');
      console.warn('CET-6 progress read:',error.code||error.message);
    });
    displayStatus(connection);
    drain(connection);
  }
  window.cet6Progress.record=(i,field,value)=>{
    if (!session) return;
    rememberOperation(session,[{word:words[i],field,value}]);
    displayStatus(session);
    drain(session);
  };
  button.addEventListener('click',async()=>{
    if (session) {displayStatus(session);drain(session);return;}
    button.disabled=true;
    try {await signInWithPopup(auth,provider);}
    catch (error) {
      note(error.code==='auth/popup-blocked'?'请允许浏览器弹出 Google 登录窗口，再点一次。':'登录未完成，请重试。');
      button.disabled=false;
    }
  });
  logout.addEventListener('click',()=>signOut(auth).catch(()=>note('退出失败，请重试。')));
  window.addEventListener('online',()=>{if(session){displayStatus(session);drain(session);}});
  window.addEventListener('offline',()=>{if(session)displayStatus(session);});
  window.addEventListener('focus',()=>{if(session)drain(session);});
  setInterval(()=>{if(session && session.queue.size)drain(session);},20000);
  onAuthStateChanged(auth,connect,()=>{button.disabled=false;note('无法读取登录状态，请刷新后重试。');});
  button.hidden=false;
}
